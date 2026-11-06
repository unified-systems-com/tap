# tap_web Chart Panel Specification

## Philosophy

TAP needs a way to render charts on dashboard pages. There are three reasonable shapes for this:

1. **Each plugin ships its own charting code.** Worst path. Plugins re-vendor a charting library, settle on incompatible chart shapes, and the platform ends up with three different ways to render a bar chart.
2. **A single domain-specific chart panel per plugin** (e.g. `KsiViolationTrendPanel`). Better, but each new chart needs Python + a new template; the per-chart fanout grows quickly.
3. **A single generic chart panel type owned by `tap_web`** that accepts a chart specification and renders it. Plugins consume it like they already consume `viewer`, `table`, `flip`, and `history`. New chart types are GRIFT changes, not Python changes.

This spec describes (3). The panel type is owned by `tap_web` so any plugin can drop a chart on any page without taking a dependency on a domain plugin. The renderer is **Apache ECharts** (Apache 2.0 licensed, vendored locally per the same pattern as Tabulator).

The panel is **declarative and config-only**. A Panel's `config` carries an Apache ECharts `option` (JSON, never code) and a few small data-shaping keys; a `USES_SEARCH` edge binds it to ONE Search, exactly as the Stat Cards panel is bound (`req-web-stdpanel-statcards`). The panel runs the Search, injects the rows as the chart's dataset and draws. A project builds a chart page from data alone: a Search, a Panel node and an edge. No per-chart Python and no per-chart JavaScript.

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
| 4. | Config-Only         | A chart is JSON on a Panel node plus a Search; no per-chart Python or JavaScript |
| 5. | Data, Not Code      | The option is data: anything that could run, fetch or inject is rejected before a chart is drawn |
| 6. | Honest Gaps         | No rows, a bad config, an unparseable value and a cut row each say so on the page; nothing is drawn as 0 or left blank |
| 7. | Themed, Accessible  | Colours come from design tokens (light and dark); the chart is labelled and its data is in a table for assistive technology |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panels-chart-panel-type | [Chart Panel Type](#chart-panel-type) | Implemented | `ChartPanelType` registered under slug `chart`; ECharts then `chart-panel.js` as panel assets |
| req-web-panels-chart-asset-vendor | [Vendored ECharts Asset](#vendored-echarts-asset) | Implemented | ECharts 6.0.0 from the npm lockfile into the image, version pinned |
| req-web-panels-chart-config | [Chart Config](#chart-config) | Implemented | `CHART_CONFIG_SCHEMA`: `option` plus `series_by`, `hierarchy`, `types`, `sort`, `limit`, `color_map`, sizing and texts; every entry described |
| req-web-panels-chart-safety | [Option Safety](#option-safety) | Implemented | The option is data: no code-like strings, plain-template formatters, no external references, closed series types, size caps |
| req-web-panels-chart-data | [Rows To Dataset](#rows-to-dataset) | Implemented | Search rows injected as `option.dataset`; per-field coercion; unparseable values are stated gaps; `sort`, `limit`, `max_rows` |
| req-web-panels-chart-series-by | [Series Pivot](#series-pivot) | Implemented | `series_by`: one series per distinct value, for stacked / grouped bars and multi-line |
| req-web-panels-chart-hierarchy | [Hierarchy](#hierarchy) | Implemented | `hierarchy`: rows with a path of fields become a tree for treemap / sunburst |
| req-web-panels-chart-render | [Chart Rendering](#chart-rendering) | Implemented | Server-rendered frame with data in attributes; empty, error and notice states; hidden data table; labelled mount |
| req-web-panels-chart-theme | [Drawing, Theme And Resize](#drawing-theme-and-resize) | Implemented | `chart-panel.js`: design tokens into an ECharts theme, `color_map`, `aria`, redraw on theme change and resize |
| req-web-panels-chart-click | [Chart Click-Through](#chart-click-through) | Implemented | `click.row_url_template`: clicking a bar or scatter item navigates to a same-origin URL filled from that item's row; pointer cursor; a real link per row in the hidden table for the keyboard |
| req-web-panels-chart-style | [Chart Styling](#chart-styling) | Implemented | Tokens with light and dark values, shared with the Stat Cards tones; frame, slot height, hidden table |

---

### Chart Panel Type
----
RID: `req-web-panels-chart-panel-type`

Status: `Implemented`

The chart panel is a tap_web-owned panel type alongside `viewer`, `table`, `flip`, `history` and `stat-cards`.

#### Implementation
- Class: `ChartPanelType` at `tap_web/panels/chart/__init__.py`; the config schema and safety rules are in `config.py`, the rows-to-option transforms in `transform.py`, the shared Search-rows data path (also used by Stat Cards) in `tap_web/panels/search_rows.py`.
- `slug = "chart"`, `label = "Chart"`, `view = "tap_web/panels/chart.html"`, `editor_view = ""`.
- `css = ["tap_web/css/panel-chart.css"]`; `js = ["tap_web/js/lib/echarts.min.js", "tap_web/js/chart-panel.js"]`. The page pipeline emits scripts in list order, so ECharts is present before `chart-panel.js` runs.
- `config_defaults = {"max_rows": 500, "height": 320}`; the one required key, `option`, has no default.
- Registered in `TapWebConfig.ready()` via `panel_type_registry.register("chart", ChartPanelType)`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-panel-type-1 | Type Registration | Implemented | `ChartPanelType` is registered under slug `chart`. | Registry: `panel_type_registry` |
| req-web-panels-chart-panel-type-2 | Assets Declared And Shipped | Implemented | The type declares its stylesheet and its scripts, ECharts first; the in-tree ones exist in `tap_web/static`, and the page pipeline collects them from the type. | `js/lib/*` is vendored into the image |
| req-web-panels-chart-panel-type-3 | tap_web Owned | Implemented | The panel type lives in `tap_web`, not in a domain plugin. | Goal 1 |

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

### Chart Config
----
RID: `req-web-panels-chart-config`

Status: `Implemented`

`Panel.config` is JSON that validates against `CHART_CONFIG_SCHEMA`. Fields are named by the RETURN alias of the Search's rows; nothing names a value, node or tool.

#### Implementation
- `option` (required): the ECharts option. Rows arrive as `option.dataset` (`dimensions` = the row keys, `source` = the rows), so series pick fields with `encode`.
- `series_by`, `hierarchy`: see `req-web-panels-chart-series-by`, `req-web-panels-chart-hierarchy`.
- `types`: `{field: number | time | category}` coercion, see `req-web-panels-chart-data`. `sort` `{field, order}`, `limit`, `max_rows`.
- `color_map`: `{field?, map: {value: token}, default?}`. Tokens are design tokens: `critical`, `high`, `medium`, `low`, `info`, the Stat Cards tones `good`, `warn`, `bad`, `neutral`, `muted`, and the categorical `accent-1` to `accent-8`.
- `height`: pixels (120-1200, default 320) or `slot` (fill the page slot, at least 240px). The width is always the container's.
- `empty_text`, `null_text`, `blank_text`, `aria_label`, `hide_header`.

#### Example (stacked bar, severity by state)
```json
{"option": {"tooltip": {"trigger": "axis"}, "legend": {}, "xAxis": {"type": "category"}, "yAxis": {"type": "value"},
            "series": [{"type": "bar", "stack": "total"}]},
 "series_by": {"category": "sev", "series": "tool", "value": "c"},
 "color_map": {"map": {"grype": "accent-1", "trivy": "accent-2"}}, "height": 300}
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-config-1 | Strict Schema | Implemented | `option` is required and any undeclared key is rejected. | |
| req-web-panels-chart-config-2 | Closed Vocabulary | Implemented | Colour tokens, field types, sort orders and `slot` are the named sets; heights, limits and row caps are bounded; malformed values are rejected. | |
| req-web-panels-chart-config-3 | Self-Describing | Implemented | The schema and every entry of it, including the nested `series_by`, `hierarchy`, `color_map` and `sort` entries, carry a `description`. | Repo rule: JSON structures require descriptions. |
| req-web-panels-chart-config-4 | No Domain Values | Implemented | Nothing in the schema enumerates a domain value, node id or tool name; the only enums are the vocabularies above. | |

### Option Safety
----
RID: `req-web-panels-chart-safety`

Status: `Implemented`

The `option` is data, never code. `validate_config` rejects anything that could run, fetch or inject before a chart is drawn; a rejected config renders a stated error (`req-web-panels-chart-render-3`).

#### Implementation
- Any string anywhere in the option that looks like code (`function (...)`, `=>`, `eval(`, `new Function`, `javascript:`, `<script`, `url(`) is rejected. JSON cannot carry a function, so a function in an option is always a string and always caught.
- Any key ending in `formatter` must be a string template (`{b}: {c}`) with no `<` or `>`; objects and numbers are rejected. ECharts HTML-encodes the values substituted into a string template and into its default tooltip, so row values that reach tooltips and labels are escaped.
- With a series that reads the dataset through `encode` (or with `series_by`), `{c}` in a formatter is rejected: it is the whole row and prints `[object Object]`. Use `{@field}` (the row field named by the RETURN alias); `{b}` (the item name) and `{d}` (a pie's percent) work as usual.
- Strings naming an external or embedded resource (`http:`, `https:`, `//`, `data:`, `file:`, `image://`) are rejected: the panel makes no fetch. The keys `link`, `sublink`, `extraCssText` and `className` (navigation, CSS injection) are rejected.
- Series types are a closed list: bar, line, pie, scatter, treemap, sunburst, heatmap, funnel, gauge, radar. `custom` (needs a render function), `map`, `lines` and `graph` are outside it.
- `dataset` is rejected in the option: the panel owns it.
- The option is capped at 32768 bytes of JSON and 14 levels of nesting.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-safety-1 | No Code-Like Strings | Implemented | A string that looks like a function, an arrow, `eval`, `javascript:`, a script tag or `url(` is rejected wherever it sits; ordinary text containing the word is not. | |
| req-web-panels-chart-safety-2 | Plain Template Formatters | Implemented | A `formatter` must be a template string without markup. | |
| req-web-panels-chart-safety-3 | No External References | Implemented | External or embedded resource strings and the navigating / CSS-injecting keys are rejected. | |
| req-web-panels-chart-safety-4 | Size Caps | Implemented | The option's byte size and nesting depth are capped. | Like Stat Cards `max_cards` |
| req-web-panels-chart-safety-5 | Closed Series Types | Implemented | Only the listed series types are accepted. | |
| req-web-panels-chart-safety-7 | Row Value Templates | Implemented | `{c}` in a formatter is rejected when a series uses `encode` or `series_by`, with the `{@field}` form named in the error; `{@field}` is accepted. | |
| req-web-panels-chart-safety-6 | Panel Owns The Dataset | Implemented | `option.dataset` in the config is rejected. | |

### Rows To Dataset
----
RID: `req-web-panels-chart-data`

Status: `Implemented`

The panel reads the bound Search's `rows` through `fetch_panel_rows` (the Stat Cards data path: the earliest `USES_SEARCH` edge, `execute_search`, page inputs from the Search's `input_schema`), then coerces, orders and caps them before ECharts sees them.

#### Implementation
- The Gryphon data lane returns some numbers and datetimes as text (`"8.2"`, `"2026-09-29 15:32:23.605000+00:00"`). `types` declares each field: `number` reads numeric text as a number, `time` reads any ISO-8601 text or datetime as a UTC instant (`...Z`; a naive value is UTC), `category` is text. Untyped values pass through JSON-safe (datetimes as UTC ISO text, decimals as numbers).
- A typed value that does not parse becomes null (a gap in the chart) and is counted in a notice under the chart. It is never drawn as 0. Null and empty-string stay as the grid's unobserved / observed-empty; zero is a value.
- `sort` orders rows (numbers by value, else text; nulls last) and `limit` keeps the first N, which makes a top-N chart. `max_rows` caps what is drawn. Every cut is counted in a notice.
- A null or empty-string value in a field drawn as a label (declared `category`, a series' `encode.itemName`, or the field on a category axis) is replaced by `null_text` ("not observed") / `blank_text` ("(empty)"), so an axis, legend and tooltip name the bucket instead of drawing it nameless. Numeric and time fields keep their gaps. `color_map` keys such a bucket by that label.
- A category axis of at most 12 categories gets `axisLabel.interval: 0` (every label shown) unless the config sets an interval.
- Without `series_by` or `hierarchy`, the rows become `option.dataset = {dimensions: <row keys>, source: <rows>}`. The config's own option is never mutated.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-data-1 | Rows Are The Dataset | Implemented | Rows become `option.dataset` with the row keys as dimensions. | |
| req-web-panels-chart-data-2 | Typed Coercion | Implemented | `number` and `time` fields are coerced from text; `category` is text. | Real Gryphon rows carry text numbers |
| req-web-panels-chart-data-3 | Gaps Are Stated | Implemented | An unparseable typed value is null and counted in a notice; null, empty and zero are preserved. | |
| req-web-panels-chart-data-4 | Sort Then Limit | Implemented | `sort` then `limit` give a top-N, direction by `order`, nulls last, and the cut rows are counted. | |
| req-web-panels-chart-data-5 | Row Cap | Implemented | More rows than `max_rows` draw `max_rows` and a notice counts the rest. | |
| req-web-panels-chart-data-6 | Unobserved Labels | Implemented | A null or empty label value is replaced by `null_text` / `blank_text`; numeric fields keep their gaps. | |
| req-web-panels-chart-data-7 | Every Label Shown | Implemented | A category axis of up to 12 categories gets `axisLabel.interval: 0`, unless configured. | |

### Series Pivot
----
RID: `req-web-panels-chart-series-by`

Status: `Implemented`

A plain dataset cannot make one series per value of a field, which is what stacked and grouped bars and multi-line charts need. `series_by: {category, series, value, order?, fill?, overrides?}` pivots the rows.

#### Implementation
- `option.series` holds exactly one template series (bar or line). One series is made per distinct value of the `series` field, named by the value, copying the template (`stack`, `areaStyle`, ...), with `encode` set from the axes: the category field goes on the axis that is `category` or `time` and the value on the other (a horizontal bar has the category on `y`).
- The dataset becomes wide: one entry per category with one dimension per series; `value` fields are summed when a pair repeats; a pair with no row is `fill` (default 0; `null` leaves a gap). `order` sets the drawing and stack order; unlisted values follow in first-seen order.
- `overrides` is a mapping from a series value (the line's name) to a partial ECharts series object, deep-merged onto the template for that one series (objects merge key by key, anything else replaces), so one line can differ from the rest: the template carries the muted default and the override restores the emphasised line, e.g. `{"Overall": {"lineStyle": {"width": 6, "opacity": 1}, "z": 10}}`. An override may not set `name`, `type`, `encode`, `data` or `dataset` (the pivot owns them); it passes the same safety rules as `option`. A key matching no series is ignored.
- Null and empty categories or series names are labelled with `null_text` / `blank_text`, not dropped. On a time axis the categories stay instants and are sorted. Rows with no numeric `value` are counted in a notice.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-series-by-1 | One Series Per Value | Implemented | Each distinct `series` value becomes a series copied from the template; duplicates are summed; `order` sets the order. | |
| req-web-panels-chart-series-by-2 | Fill And Labels | Implemented | A missing pair is `fill`; null categories are labelled; rows with no number are counted, not zeroed. | |
| req-web-panels-chart-series-by-3 | Orientation | Implemented | The category field goes on whichever axis is the category axis, so horizontal bars work. | |
| req-web-panels-chart-series-by-4 | Time Axis | Implemented | On a time axis categories are kept as instants and sorted. | |
| req-web-panels-chart-series-by-5 | Needs A Template | Implemented | `series_by` without exactly one bar or line series is rejected at validation. | |
| req-web-panels-chart-series-by-6 | Per-Series Overrides | Implemented | `series_by.overrides[value]` is deep-merged onto the template for that series only; other series are unchanged and the template is not mutated. | |
| req-web-panels-chart-series-by-7 | Overrides Are Safe Data | Implemented | An override that is not an object, sets `name`, `type`, `encode`, `data` or `dataset`, or breaks an option safety rule (code-like string, `{c}` formatter, external reference) is rejected; the schema entry carries a description. | |

### Hierarchy
----
RID: `req-web-panels-chart-hierarchy`

Status: `Implemented`

`hierarchy: {path, value?}` turns rows into a tree for treemap and sunburst series.

#### Implementation
- One level per `path` field, outermost first (1 to 6 fields); the last field names the leaf. Each leaf's size is the `value` field, summed over repeated paths; with no `value` each row counts 1.
- The tree is set as `data` on every treemap or sunburst series that has none. Null and empty levels are labelled; rows with no numeric value are counted in a notice.
- `hierarchy` needs a treemap or sunburst series and cannot be combined with `series_by`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-hierarchy-1 | Rows Become A Tree | Implemented | Rows nest by the path fields, leaves sized by the value field, and the tree lands on the treemap or sunburst series. | |
| req-web-panels-chart-hierarchy-2 | Counts And Labels | Implemented | Without `value` each row counts 1; null and empty levels are labelled. | |
| req-web-panels-chart-hierarchy-3 | Flat Path | Implemented | A one-field path gives flat leaves. | |
| req-web-panels-chart-hierarchy-4 | Needs A Hierarchical Series | Implemented | `hierarchy` without a treemap or sunburst series, or with `series_by`, is rejected. | |

### Chart Rendering
----
RID: `req-web-panels-chart-render`

Status: `Implemented`

Server-rendered frame; `chart-panel.js` draws it (`req-web-panels-chart-theme`). Template `tap_web/panels/chart.html`.

#### Implementation
- Wrapper `<div class="tap-panel tap-panel--chart">`; the shared panel header unless `hide_header`.
- A `<figure data-tap-chart>` carries the built option in `data-tap-chart-option` and the colour map in `data-tap-chart-colors`: attributes, auto-escaped, so the fragment emits no inline script. The mount is `<div class="tap-chart__mount" id="tap-chart-{entity_id}" role="img" aria-label="...">`.
- The accessible name is `<aria_label or panel name>: N rows. The same data is in the table that follows.` The same rows are in a visually hidden table (every column, with a caption) so the data is available to assistive technology.
- No rows: the `empty_text` (default "No results.") in a bordered box, never a blank frame. An invalid config, no linked search, a failed search or a search that returns nodes each render an alert with the reason. Notices (gaps, cut rows) print under the chart. A drawing failure in the browser shows a visible message in the frame.
- Height from `height` (pixels via a CSS variable, or `slot`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-render-1 | Rows Reach The Chart | Implemented | A real Gryphon search over seeded grid rows gives the chart its dataset, in the standard wrapper with the stable mount id. | |
| req-web-panels-chart-render-2 | Empty Is Stated | Implemented | No rows shows `empty_text` and no chart. | |
| req-web-panels-chart-render-3 | Errors Are Stated | Implemented | No linked search, an invalid config, or a search returning nodes renders an alert with the reason. | |
| req-web-panels-chart-render-4 | Escaped | Implemented | Row values are auto-escaped and the fragment emits no inline script. | `req-web-panel-render-content.sec` |
| req-web-panels-chart-render-5 | Labelled With Its Data | Implemented | The mount is labelled with what it shows and the row count, and the same rows are in a captioned table. | |
| req-web-panels-chart-render-6 | Header And Height | Implemented | `hide_header` omits the heading; `height` sets pixels or `slot`. | |
| req-web-panels-chart-render-7 | Notices | Implemented | Gaps and cut rows are stated under the chart. | |

### Drawing, Theme And Resize
----
RID: `req-web-panels-chart-theme`

Status: `Implemented`

`tap_web/static/tap_web/js/chart-panel.js` draws every `[data-tap-chart]`. It names no field, panel or chart type and never evaluates anything from the option.

#### Implementation
- Data labels (`series.label`, and the pie, funnel, heatmap, treemap and sunburst defaults) are solid, outline-free text: the theme sets `textBorderWidth: 0` and the text colour for them, and a label the config declares has whatever it leaves unset filled the same way. ECharts' default text border outlined them on the dark frame. A config that sets `color` or `textBorderWidth` itself is left alone (`req-web-panels-chart-theme-5`).
- Colours are read from the `--tap-chart-*` custom properties on the panel root into an ECharts theme (text, axis, grid, tooltip, series palette `accent-1..8`), so a chart follows the page's light or dark tokens.
- `color_map` resolves tokens to colours and colours series named by a mapped value and, for bar, pie, scatter, funnel, treemap and sunburst series driven by `encode`, each data item by the row's `field` value (or its name); `series_by` defaults `field` to its `series` field. A series with its own `itemStyle.color` is left alone.
- `aria` is switched on, with the server's label as its description (ECharts' generated text misreads dataset-encoded series).
- The chart is redrawn when the viewer's colour scheme changes or `data-theme` / `class` on `<html>` change (the page-wide switch that sets `data-theme` is `spec-web-theme.md`), and resized by a `ResizeObserver` on the mount and on window resize. It is initialised after an HTMX settle, and disposed once its element leaves the page.
- A failure (library missing, bad JSON) shows `This chart could not be drawn: ...` in the frame and sets `data-tap-chart-ready="error"`.
- Proven in a real browser; the repo has no JS test runner. Test-side, the colour map travels as data (`req-web-panels-chart-theme-1`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-theme-1 | Colour Map Travels As Data | Implemented | The colour map reaches the browser as data, with `series_by` defaulting its field. | Browser: colours applied |
| req-web-panels-chart-theme-2 | Tokens Not Literals | Implemented | Chart colours come from the design tokens, not from literals in the script or config. | Proven in a browser |
| req-web-panels-chart-theme-3 | Follows Theme And Size | Implemented | The chart redraws on a colour-scheme change and resizes with its container. | Proven in a browser |
| req-web-panels-chart-theme-4 | Visible Failure | Implemented | A drawing failure is shown in the frame, not only in the console. | Proven in a browser |
| req-web-panels-chart-theme-5 | Solid Data Labels | Implemented | Data labels are solid filled text with no outline, in the theme's text colour, in light and dark, for every series type that draws them, unless the config's own `label` sets `color` or `textBorderWidth`. | ECharts' default text border outlined the numbers on the dark frame. Computed through the chart's own model in a real browser: `textBorderWidth` 0. |

### Chart Click-Through
----
RID: `req-web-panels-chart-click`

Status: `Implemented`

A chart can navigate: clicking a bar or a scatter point opens a page chosen by that item's row. It is panel configuration, never per-page code.

#### Implementation
- Config `click: {"row_url_template": "/path?x={alias}"}`. The template is a same-origin path (`ROW_URL_TEMPLATE_PATTERN`, the rule of the Table panel's `row_url_template`, `req-web-stdpanel-table-rows-5`, one implementation in `tap_web/panels/row_url.py`); `{alias}` placeholders take the row's values, each URL-encoded as one component. A row whose placeholder has no value (absent, null, empty) has no link.
- The server fills the URL: `build_option` puts it in the dataset row as `_url` (not a drawn dimension) and gives `bar` and `scatter` series `cursor: "pointer"` (a series' own `cursor` stays). `chart-panel.js` only navigates to the clicked item's `_url`, after re-checking that it is a same-origin path; a Ctrl or Cmd click opens a new tab. Other series types are not clickable.
- With `series_by` the item is a category, so only the `category` field may be a placeholder. `click` with `hierarchy` is rejected (a tree item is not a row), as is `click` with no bar or scatter series.
- Keyboard and assistive technology: the canvas is not focusable, so when any row has a URL the visually hidden data table gains a `Link` column with a real `<a href>` per clickable row (`Open <first column>`); the table is revealed in place while a link has focus.

Example (a bar per component; the page the bar opens is the consumer's data):

```json
{"option": {"xAxis": {"type": "value"}, "yAxis": {"type": "category"},
            "series": [{"type": "bar", "encode": {"x": "open", "y": "component"}}]},
 "click": {"row_url_template": "/vulnerabilities/component?component_id={cid}"}}
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-click-1 | Template Is A Same-Origin Path | Implemented | `click.row_url_template` must be a same-origin path (never `//host`, a scheme, whitespace or a backslash); the `click` object is strict and every entry is described. | The Table panel's pattern. |
| req-web-panels-chart-click-2 | Rows Carry Their URL | Implemented | Each dataset row carries its `_url`, URL-encoded; a row with a missing value has none; an unvalidated unsafe template yields none; `_url` is not a dimension; with `series_by` each category has one. | |
| req-web-panels-chart-click-3 | Bar And Scatter Only, Pointer Cursor | Implemented | Bar and scatter series get the pointer cursor (a series' own cursor stays); `click` needs one; it excludes `hierarchy`; with `series_by` only the category may be a placeholder. | Without `click` nothing is added. |
| req-web-panels-chart-click-4 | Keyboard Route | Implemented | A click-through chart's hidden data table has a `Link` column with a real link per clickable row; without `click` there is none. | Proven in a real browser: Tab and Enter navigate. |
| req-web-panels-chart-click-5 | Click Navigates | Implemented | A click on a bar or scatter item opens its `_url`; a click on empty space does nothing; Ctrl or Cmd opens a new tab. | Proven in a real browser: the resulting URL read after the click. |

### Chart Styling
----
RID: `req-web-panels-chart-style`

Status: `Implemented`

Trace: `non-python` — tap_web/static/tap_web/css/panel-chart.css

#### Implementation
`panel-chart.css`: tokens on the panel root with dark values under `prefers-color-scheme: dark` and `[data-theme="dark"]` (guarded by `[data-theme="light"]`), the same mechanism as `stat-cards.css`. `good`, `warn`, `bad`, `muted` are the Stat Cards tone colours (`neutral` is darkened in light mode to reach 3:1 as a graphic); `critical`, `high`, `medium`, `low`, `info` are the severity words. Measured with the WCAG relative-luminance formula against the frame background: every colour token has at least 3:1 and the text tokens at least 4.5:1, in both schemes. The frame is a bordered card; the mount is 100% wide; `tap-chart--slot` fills the slot. The data table is visually hidden but stays in the accessibility tree.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-chart-style-1 | Light And Dark Tokens | Implemented | Colours are tokens with light and dark values. | |
| req-web-panels-chart-style-2 | Fills Its Slot | Implemented | The chart is container-wide and `slot` height fills the page slot. | |
| req-web-panels-chart-style-3 | Hidden Table Does Not Overflow | Implemented | The data table is hidden inside a clipped wrapper and never widens the page at phone width. | |

## Out Of Scope

- A typed in-page editor (`editor_view` is empty; the generic panel editor edits `config` as JSON).
- Click-through from series other than bar and scatter, and from a hierarchy item.
- Series types outside the closed list (`custom`, `map`, `lines`, `graph`).
- Streaming or auto-refresh of the data.

## Future Work

- **Subset bundle.** Once the in-use chart types are stable, swap the full ECharts build for a smaller subset.
- **Editor integration.** A panel-editor surface for authoring and previewing chart options.
- **Other aggregates.** Per-bucket time grouping and `SUM` / `AVG` arrive with Gryphon; today a time series groups on the stored instant.

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
