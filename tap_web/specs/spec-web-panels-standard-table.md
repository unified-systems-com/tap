# Table Panel Specification

## Philosophy

The Table Panel is the first standard panel that turns TAP search results into a reusable data exploration surface. It should stay within the standard Panel contract while proving a richer pattern than the Text Panel: code-backed rendering, search binding, client-side table behavior, and pagination.

The first version should optimize for predictable behavior over maximum flexibility. It should consume a Search object, render node results into a table, and establish a clean contract for how future table variants handle mixed node types, richer formatting, row actions, and edge-centric result sets.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Search-Bound | Table panels display the results of a linked Search object rather than embedding ad hoc query logic |
| 2. | Standardized | Table behavior is defined as a built-in TAP Web panel type, not left to one-off plugin implementations |
| 3. | Predictable | Mixed-type node results have a deterministic default display strategy |
| 4. | Paginated | Table panels support page-wise traversal of large result sets |
| 5. | Self-Contained | Required JavaScript ships from TAP static assets; no CDN dependency is allowed |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-stdpanel-table-config | [Table Configuration](#table-configuration) | Proposed | Panel config object JSON Schema; the single reference for all Table Panel options stored in `Panel.config` |
| req-web-stdpanel-table | [Table Panel Type](#table-panel-type) | Proposed | Built-in panel type using Tabulator for browser-side table rendering |
| req-web-stdpanel-table-search | [Table Search Binding](#table-search-binding) | Proposed | Panel binds to exactly one Search via `USES_SEARCH` (`Panel -> Search`) |
| req-web-stdpanel-table-columns | [Node Result Column Strategy](#node-result-column-strategy) | Proposed | V1 defaults to a common-metadata column set for mixed node results |
| req-web-stdpanel-table-pagination | [Table Pagination](#table-pagination) | Proposed | Table panel supports paginated traversal backed by TAP search pagination |
| req-web-stdpanel-table-render | [Table Rendering Flow](#table-rendering-flow) | Proposed | V1 executes the linked Search server-side and mounts Tabulator from shipped static JS |
| req-web-stdpanel-table-edit | [Table Panel Editor](#table-panel-editor) | Proposed | Standard editor configures linked search and table behavior flags |
| req-web-stdpanel-table-row-nav | [Row Navigation](#row-navigation) | Implemented | Clicking a node-mode table row navigates to the TAP object viewer for that entity |

---

### Table Configuration
----
RID: `req-web-stdpanel-table-config`
Status: `Proposed`

The Table Panel stores all display and behavior options in the standard `Panel.config` JSONField. The config object conforms to a fixed JSON Schema — no arbitrary keys are permitted. This requirement is the single reference for every option that can be stored in a Table Panel's config.

#### Status Details
New requirement establishing the authoritative config contract for Table Panel instances. All editor fields and runtime behavior must trace back to a key defined here.

#### Implementation
- Table Panel config is validated against the schema below before each save.
- `additionalProperties: false` — unrecognized keys are rejected.
- Default values are applied when a key is absent.
- The linked Search's `max_limit` remains authoritative over `default_limit`; if `default_limit` exceeds it the search service clamps silently.

#### Config JSON Schema

The authoritative schema is `TABLE_CONFIG_SCHEMA` in `tap_web/panels/table_panel/__init__.py`; this block mirrors it.

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "column_mode": {
      "type": "string",
      "enum": ["common_metadata"],
      "description": "Column rendering strategy when no explicit `columns` are given. V1 supports only common_metadata."
    },
    "default_page_size": {
      "type": "integer",
      "minimum": 1,
      "maximum": 500,
      "description": "Default rows per page before the user selects another size. Clamped to the linked Search's max_limit; defaults to 100 when absent."
    },
    "quick_filter": {
      "type": "boolean",
      "description": "When true, render a quick-filter search box top-right of the table that live-filters the loaded rows client-side across all displayed columns. Filters the current page's rows only — pair with a page size that loads the full set when whole-table filtering is intended."
    },
    "columns": {
      "type": "array",
      "minItems": 1,
      "description": "Explicit column specs; overrides column_mode. Each maps to one client-side table column.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["field", "title"],
        "properties": {
          "field": {"type": "string", "minLength": 1, "description": "Dotted path into the node envelope, e.g. `name` or `data.<field>`."},
          "title": {"type": "string", "description": "Column header text."},
          "width": {"type": "integer", "minimum": 20, "maximum": 800},
          "widthGrow": {"type": "integer", "minimum": 1, "maximum": 5},
          "formatter": {
            "type": "string",
            "enum": ["plaintext", "datetime", "tickCross", "tickDash", "ciaLevel", "ellipsisSuffix", "json", "passFailBadge", "conclusionBadge", "externalLink", "painBadge", "arrayCount"],
            "description": "Named client-side cell renderer; see Column Formatters below."
          },
          "tooltip": {"type": "string", "enum": ["full_value"]},
          "headerSort": {"type": "boolean"}
        }
      }
    },
    "group_by": {
      "type": "object",
      "additionalProperties": false,
      "required": ["field", "rules"],
      "description": "Declarative row grouping into sections; see Row Grouping below.",
      "properties": {
        "field": {"type": "string", "minLength": 1, "description": "Dotted path whose value is prefix-matched to choose a section."},
        "rules": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["prefix", "label"],
            "properties": {
              "prefix": {"type": "string", "minLength": 1},
              "label": {"type": "string", "minLength": 1}
            }
          }
        },
        "default_label": {"type": "string", "minLength": 1, "description": "Section label for rows that match no rule."}
      }
    }
  }
}
```

`column_mode` options:
- `common_metadata` — fixed column set derived from current entity-spine metadata fields. Canonical entity metadata terminology is `name`, not `display_name` or `title`. This is the only supported mode in V1, and the fallback when no explicit `columns` are given.

#### Column Formatters
`columns[].formatter` selects a named client-side renderer (defined in `panel-table.js`); string names keep the config declarable with no inline JS. Available formatters:
- `plaintext` — raw string value (default).
- `datetime` — local timestamp with zone disclosure, rendered through the shared time-display helper (`spec-web-time-display.md`, `req-web-time-single-helper`). The incoming value is UTC ISO-8601; the formatter localizes to the viewer's browser zone and discloses the zone (`req-web-time-local-display`, `req-web-time-zone-disclosure`).
- `tickCross` — `✓` / `✕` / `–` for true / false / null-or-absent.
- `tickDash` — `✓` for true, a neutral `–` otherwise; for boolean columns where a "no" is unremarkable rather than a fault.
- `ciaLevel` — compact impact level: `low → L`, `moderate → M`, `high → H`, anything else (not-applicable, blank) → a neutral `–`; color-coded by severity.
- `ellipsisSuffix` — last 8 characters with a leading ellipsis; for long opaque identifiers.
- `json` — compact JSON, truncated.
- `passFailBadge` — `PASS` / `FAIL` pill.
- `conclusionBadge` — GitHub-shaped terminal conclusion pill: `success` green, `failure` / `timed_out` / `startup_failure` red, every other value (`cancelled`, `skipped`, `neutral`, …) a neutral grey, and an absent value a `–` — an empty cell reads as *not observed*, never as quietly fine.
- `externalLink` — an `http(s)` URL rendered as an anchor opening in a new tab (`rel="noopener noreferrer"`), scheme stripped and truncated for display; any non-http(s) value renders as escaped text so a hostile value never becomes a `javascript:` href.
- `painBadge` — colored pill for ordinal severity codes.
- `arrayCount` — count of array items, `–` when empty.

#### Row Grouping
When `group_by` is present, rows are partitioned into ordered sections. Each row is classified by matching its `field` value against the `rules` in order; the first rule whose `prefix` the value starts with assigns the row's section `label`. Rows matching no rule fall into `default_label`. Sections render in rule order (the `default_label` section last), with rows sorted within each section by the grouping field. Section headers show a live count that re-tallies as a `quick_filter` narrows the set. The section taxonomy (the prefix→label rules) lives in the panel's config, not in the platform JS — so the consumer owns its grouping vocabulary.

#### Development
Every future Table Panel option (per-type split mode, row actions, richer renderers) must be added to this schema and this section first. The schema is the contract; everything else follows from it. New `columns[].formatter` values are added to the enum here and implemented as a named renderer in `panel-table.js` in the same change.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-config-1 | Config Is Validated On Save | Proposed | Table Panel config is validated against the defined JSON Schema before each save. | Uses `jsonschema.validate`; raises `ValidationError` on failure. |
| req-web-stdpanel-table-config-2 | No Arbitrary Keys | Proposed | `additionalProperties: false` — unrecognized config keys are rejected at save time. | |
| req-web-stdpanel-table-config-3 | Defaults Applied | Proposed | `column_mode` defaults to `common_metadata`; `default_page_size` defaults to `100` when absent. | |
| req-web-stdpanel-table-config-4 | Search Cap Respected | Proposed | `default_page_size` is advisory; the search service `max_limit` takes precedence at execution time. | Cross-ref `req-web-stdpanel-table-pagination-4`. |

#### Future
Add `per_node_type_tables` (separate tables per entity type) and per-row actions as config keys once each is specced and approved. (Explicit `columns` with named formatters, declarative `group_by` row sections, and the `quick_filter` search box are implemented above.)

### Table Panel Type
----
RID: `req-web-stdpanel-table`
Status: `Proposed`

The Table Panel is a built-in standard panel type that renders search-backed rows using the Tabulator JavaScript library.

#### Status Details
New standard proposed as its own specification so the behavior can grow independently from the catalog-level `spec-web-panels-standard.md`.

#### Implementation
- The Table Panel lives in `tap_web/panels/table_panel/`.
- It is registered in `panel_type_registry` as a built-in standard panel type.
- It uses the standard Panel object contract from `spec-web-panel.md`:
  - `view`
  - optional `editor_view`
  - `config`
  - `js` / `css`
  - `editor_js` / `editor_css`
- The browser table implementation uses Tabulator.
- Required Tabulator assets are stored in TAP-managed static files and referenced through panel asset lists.
- Vendored third-party table assets should live under a static library path such as `js/lib/`.
- Table-panel-specific browser glue code should live in a dedicated static file such as `js/panel-table.js`.
- The panel must not depend on CDN-hosted or other internet-hosted assets.
- The panel must not embed inline JavaScript in rendered HTML; browser behavior is attached through shipped static assets.

#### Development
Treat the first Table Panel as a reference implementation for search-backed interactive panels. Keep the contract explicit so later standards can add filters, row actions, or richer renderers without redefining core table behavior.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-1 | Built-In Table Type Exists | Proposed | TAP Web provides a built-in Table Panel type under `tap_web/panels/table_panel/`. | |
| req-web-stdpanel-table-2 | Tabulator Is Canonical Table Engine | Proposed | Standard Table Panel rendering uses Tabulator rather than an ad hoc table implementation. | |
| req-web-stdpanel-table-3 | Assets Ship Locally | Proposed | Tabulator and panel code are served from TAP static assets only. | Cross-ref `req-web-panel-static`. |
| req-web-stdpanel-table-4 | No Inline Panel JavaScript | Proposed | Table Panel behavior is implemented through referenced static files rather than inline HTML script blocks. | |
| req-web-stdpanel-table-5 | Standard Panel Contract Preserved | Proposed | Table Panel conforms to the standard Panel object contract. | |

#### Future
Consider a shared helper for standard panels that mount client-side widgets from server-rendered config payloads.

### Table Search Binding
----
RID: `req-web-stdpanel-table-search`
Status: `Proposed`

Each Table Panel is bound to a Search object through a dedicated web edge so table rendering can resolve a reusable query definition without storing search logic directly in panel config.

#### Status Details
This requirement proposes a first-class `USES_SEARCH` relationship for web panels.

#### Implementation
- A Table Panel references its data source through a `USES_SEARCH` edge.
- `USES_SEARCH` direction for Table Panels is `Panel -> Search`.
- In v1, a Table Panel should bind to exactly one Search object.
- The linked Search is executed through the TAP search service layer defined in `spec-grid-search.md`.
- The Table Panel does not bypass the search service and does not execute ORM or module search logic directly.
- Search-specific inputs remain separate from the existence of the search binding itself.

#### Development
Keep the search relationship explicit and graph-native. A link is easier to inspect, swap, and reason about than embedding search identifiers deep inside panel config.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-search-1 | Uses Search Link Exists | Proposed | A first-class `USES_SEARCH` edge type exists for linking a Table Panel to a Search. | Edge registration details TBD. |
| req-web-stdpanel-table-search-2 | Panel To Search Direction | Proposed | The canonical direction for the table search link is `Panel -> Search`. | |
| req-web-stdpanel-table-search-3 | Single Search Binding In V1 | Proposed | A Table Panel binds to one Search object by default. | |
| req-web-stdpanel-table-search-4 | Search Service Executes Query | Proposed | Table Panel data loading executes the linked Search only through the shared search service layer. | Cross-ref `req-grid-search-exec`. |
| req-web-stdpanel-table-search-5 | Search Logic Not Stored In Panel Config | Proposed | Table Panel config may store presentation settings, but not an ad hoc duplicate of the search definition. | |

#### Future
Allow a richer multi-search panel later if a single table needs merged result sets or auxiliary lookup searches.

### Node Result Column Strategy
----
RID: `req-web-stdpanel-table-columns`
Status: `Proposed`

The first Table Panel standard only guarantees node-result display. Because searches may return mixed node types, the panel requires a deterministic column strategy instead of assuming a single entity schema.

#### Status Details
This requirement captures the default behavior discussed for mixed node-type search results.

#### Implementation
- V1 Table Panel consumes node results only.
- Rows are derived from the `nodes` members of the canonical search result envelope.
- Default column mode is `common_metadata`.
- In `common_metadata` mode, the panel renders a shared column set intended to work across heterogeneous node types.
- The shared column set should include:
  - node identity
  - name
  - description
  - node type
  - last edited timestamp
  - dimensions
- `last edited` and `dimensions` are sourced from entity-spine-backed node metadata rather than invented panel-local fields.
- A future feature flag may enable a `per_node_type_tables` mode that renders separate tables for each node type.
- Until that mode exists, mixed node types stay in one table with the common metadata projection.

#### Development
Do not overfit v1 to one plugin's entity schema. The first version needs a stable fallback that works even when node payloads are heterogeneous or sparsely populated.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-columns-1 | Nodes Only In V1 | Proposed | The initial Table Panel standard displays node search results and does not yet define edge-table rendering. | |
| req-web-stdpanel-table-columns-2 | Common Metadata Default | Proposed | Mixed node-type results default to a shared metadata-oriented column set. | |
| req-web-stdpanel-table-columns-3 | Single Table Default | Proposed | Mixed node-type results render in one table by default rather than automatically splitting by node type. | |
| req-web-stdpanel-table-columns-4 | Entity Metadata Included | Proposed | The default common metadata set includes `last edited` and `dimensions` alongside identity, name, description, and node type. | |
| req-web-stdpanel-table-columns-5 | Future Split Mode Reserved | Proposed | A future feature variable may allow separate per-type tables without changing the default V1 contract. | |

#### Future
Define the canonical common metadata column set precisely once node serialization for web display is better standardized.

### Table Pagination
----
RID: `req-web-stdpanel-table-pagination`
Status: `Proposed`

Table panels support pagination and map table page changes onto TAP search pagination controls.

#### Status Details
Search pagination already exists at the search service layer; this requirement defines how the Table Panel consumes it.

#### Implementation
- The Table Panel supports paginated traversal of result rows.
- Pagination uses search `limit` and `offset` rather than slicing an already-loaded unbounded result in the browser.
- The Table Panel respects Search defaults and caps:
  - `default_limit`
  - `max_limit`
- In v1, pagination state is owned inside the panel rather than page-level shared state.
- Table UI pagination state must remain consistent with the executed search window.
- Search execution metadata needed for pagination may be derived from paginated search results and `info`.

#### Development
Use server-backed pagination semantics even if Tabulator can paginate local arrays. The point of this requirement is correct behavior on large result sets, not only a nicer front-end widget.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-pagination-1 | Pagination Supported | Proposed | Users can move through table result pages. | |
| req-web-stdpanel-table-pagination-2 | Backed By Search Limit Offset | Proposed | Table pagination translates to TAP search `limit` / `offset` execution parameters. | |
| req-web-stdpanel-table-pagination-3 | Panel-Owned State In V1 | Proposed | The first implementation keeps pagination state inside the panel rather than promoting it to page variables. | |
| req-web-stdpanel-table-pagination-4 | Search Caps Respected | Proposed | Search `default_limit` and `max_limit` remain authoritative. | |
| req-web-stdpanel-table-pagination-5 | Window Metadata Available | Proposed | Table rendering has enough metadata to show current page/window state. | |
| req-web-stdpanel-table-pagination-6 | Pagination Bar Always Rendered When Paginated | Proposed | The pagination bar renders whenever the result envelope contains pagination metadata (`count`, `limit`, `offset`), even when the result fits on a single page. | |
| req-web-stdpanel-table-pagination-7 | Boundary Buttons Disabled Not Hidden | Proposed | Prev is disabled (not absent) when `offset == 0`. Next is disabled (not absent) when `offset + limit >= count`. | |
| req-web-stdpanel-table-pagination-8 | Display Range Capped At Count | Proposed | The range label upper bound is `min(offset + limit, count)` — never exceeds total count. | |

#### Future
Consider URL-backed page state for pagination once panel/page input coordination is implemented.

### Table Panel Editor
----
RID: `req-web-stdpanel-table-edit`
Status: `Proposed`

The standard Table Panel editor configures the panel's presentation behavior and linked search relationship without exposing raw executable logic.

#### Status Details
Editor behavior is proposed but intentionally left smaller than future power-user table builders.

#### Implementation
- The Table Panel should provide an editor view.
- The editor should configure:
  - panel title
  - panel description
  - linked Search binding
  - node column strategy flags
  - pagination settings allowed at the panel layer
- The editor should not require users to paste arbitrary JavaScript or executable search code.

#### Development
Keep the first editor narrow and explicit. It should make the linked search and display mode obvious rather than becoming a generic JSON blob editor for Tabulator internals.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-edit-1 | Typed Editor Exists | Proposed | The Table Panel includes a dedicated editor flow. | |
| req-web-stdpanel-table-edit-2 | Search Binding Configurable | Proposed | The editor allows selecting or changing the linked Search binding. | Exact UX TBD. |
| req-web-stdpanel-table-edit-3 | Presentation Settings Separate From Query Logic | Proposed | The editor exposes table presentation settings without duplicating search execution logic in panel config. | |

#### Future
If search selection patterns become common, define a reusable selector component for panel editors and other web tooling.

Likely future direction:
- add a dedicated `/api/search` endpoint for executing specific Search objects
- return search results in an API-oriented graph envelope with node and edge collections
- allow table panels and other clients to move to a cleaner JSON fetch model when the web/API boundary is better defined

### Table Rendering Flow
----
RID: `req-web-stdpanel-table-render`
Status: `Proposed`

The first Table Panel rendering flow executes the linked Search server-side during panel rendering and hands the browser a bounded result payload for Tabulator to mount.

#### Status Details
This keeps the initial implementation aligned with the existing HTMX panel rendering model while still allowing later evolution toward more API-shaped refresh flows.

#### Implementation
- The panel fragment request executes the linked Search on the server.
- The rendered HTML fragment includes the table mount point and references the panel's static JS assets.
- Search results are serialized into the rendered panel fragment as embedded escaped data in a non-executable container suitable for the table glue code to consume.
- The browser-side table code initializes Tabulator from that server-provided payload.
- Periodic refresh may be supported by re-requesting the panel fragment or a later dedicated refresh endpoint, but v1 does not require a JSON-first API design.

#### Development
Server-side first fits the current panel architecture and is easier to reason about while the panel contract is still stabilizing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-render-1 | Search Runs During Panel Render | Proposed | The initial Table Panel implementation executes the linked Search during server-side panel rendering. | |
| req-web-stdpanel-table-render-2 | Browser Mount Uses Static JS | Proposed | Tabulator initialization happens in shipped static JS, not inline script blocks. | |
| req-web-stdpanel-table-render-3 | Embedded Escaped Data Payload | Proposed | V1 passes search results to browser code as embedded escaped data in the rendered panel fragment rather than inline executable JavaScript. | |
| req-web-stdpanel-table-render-4 | Refresh Path Remains Possible | Proposed | The rendering approach leaves room for periodic refresh without redefining the panel contract. | Full JSON endpoint deferred. |

### Row Navigation
----
RID: `req-web-stdpanel-table-row-nav`
Status: `Implemented`

Clicking a row in node-mode table panels navigates to the TAP object viewer for that entity.

#### Implementation
- Row click triggers `window.location.href = "/object/{entity_type}/{url_id}/"`.
- `url_id` is a `{slug}--{entity_id}` string serialized into every node payload by `_serialize_entity`.
- Navigation applies only in `node` mode; edge-mode rows do not navigate.
- A `pointer` cursor is applied to all node-mode rows to signal clickability.

#### Development
Row navigation is a read-only entrypoint to the object viewer. It must not interfere with Tabulator's own sorting, column resize, or pagination controls.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-row-nav-1 | Row Click Navigates In Node Mode | Implemented | Clicking a node-mode row navigates to `/object/{entity_type}/{url_id}/`. | `rowClick` in `panel-table.js` |
| req-web-stdpanel-table-row-nav-2 | Edge Mode Rows Do Not Navigate | Implemented | Clicking a row in edge mode does not trigger viewer navigation. | |
| req-web-stdpanel-table-row-nav-3 | Cursor Signals Clickability | Implemented | Node-mode rows display a pointer cursor. | `rowFormatter` in `panel-table.js` |
| req-web-stdpanel-table-row-nav-4 | URL ID In Node Payload | Implemented | Every serialized node carries a `url_id` field usable as the viewer URL segment. | Cross-ref `req-viz-panel-node-nav-2` |

#### Future
If multi-select row actions (bulk view, comparison) are added later, define them as an extension rather than redefining the single-click navigation contract.


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
