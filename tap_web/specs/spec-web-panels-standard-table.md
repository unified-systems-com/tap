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
| req-web-stdpanel-table-rows | [Projection Rows](#projection-rows) | Implemented | A Gryphon search that RETURNs aliases renders its `rows`: aliases are the columns, `columns[]` applies, the total is the true row count |

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
    "show_all_rows": {
      "type": "boolean",
      "description": "Whether the Rows (page size) selector offers an `All` entry. Default true. False omits it: the table stays paged, and a stored or requested `All` falls back to `default_page_size`."
    },
    "empty_text": {
      "type": "string", "minLength": 1, "maxLength": 200,
      "description": "Plain text shown when the table has no rows, in place of the generic `No results.`."
    },
    "quick_filter": {
      "type": "boolean",
      "description": "When true, render a quick-filter search box top-right of the table that live-filters the loaded rows client-side across all displayed columns. Filters the current page's rows only — pair with a page size that loads the full set when whole-table filtering is intended."
    },
    "height": {
      "type": "integer", "minimum": 160, "maximum": 2400,
      "description": "Fixed table height in px. Tabulator owns the scroll inside it and keeps the header visible; omit for a content-height table. Lets a page keep the document scrollable while each table stays a reasonable size."
    },
    "refresh_seconds": {
      "type": "integer", "minimum": 15, "maximum": 3600,
      "description": "Auto-refresh: the panel re-fetches its own fragment every N seconds through the page slot, rendering the Grafana/Kibana affordance beside the heading: a ↻ refresh-now button and a small interval selector (Off / 30s / 1m / 5m / 15m, plus the configured value) defaulting to this value; the reader's choice is remembered per panel for the browser session; nothing counts down while the table is read. Omit for a static table."
    },
    "striped": {
      "type": "boolean",
      "description": "When true, every even row gets a subtle alternating background (the `--tap-table-stripe` theme tokens, readable in light and dark). Default false: uniform rows."
    },
    "row_url_template": {
      "type": "string", "minLength": 2, "pattern": "^/(?![/\\\\])[^\\\\\\u0000-\\u0020\\u007f]*(?![\\s\\S])",
      "description": "Projection mode only: a same-origin path whose `{alias}` placeholders fill from each row (URL-encoded); a placeholder with no value leaves that row without a link. The result is the row's `_url`, which makes the row a click target. Ignored in node mode. See Projection Rows."
    },
    "chrome": {
      "type": "string", "enum": ["full", "minimal"],
      "description": "How much table furniture to draw. `full` (default): the nav bars (Showing N of M, page size, prev/next) above and below, and the quick filter when asked for. `minimal`: none of it — for a table that is one row of facts (an identity row) rather than a list to page through; the heading and the refresh status stay."
    },
    "columns": {
      "type": "array",
      "minItems": 1,
      "description": "Explicit column specs; overrides column_mode. Each item is either a leaf column (`$defs/column`, mapping to one client-side table column) or a one-level group (`$defs/column_group`: a `title` over leaf `columns`, Tabulator's grouped header) — never both.",
      "items": {"anyOf": [{"$ref": "#/$defs/column"}, {"$ref": "#/$defs/column_group"}]}
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
  },
  "$defs": {
    "column_group": {
      "type": "object",
      "additionalProperties": false,
      "required": ["title", "columns"],
      "properties": {
        "title": {"type": "string", "minLength": 1, "description": "The caption over the group."},
        "columns": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/column"}, "description": "The leaves under it; a group nests no further."}
      }
    },
    "column": {
        "type": "object",
        "additionalProperties": false,
        "required": ["title"],
        "oneOf": [{"required": ["field"]}, {"required": ["field_path"]}, {"required": ["field_paths"]}],
        "dependentRequired": {"joiner": ["field_paths"]},
        "properties": {
          "field": {"type": "string", "minLength": 1, "description": "Dotted path into the node envelope, e.g. `name` or `data.<field>`; in projection mode, a RETURN alias (e.g. `assignee`)."},
          "field_path": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}, "description": "The value's location as an array of path segments, each one key even if it contains a dot (['dimensions', 'dataclass.customer']). Use instead of `field`, never with it."},
          "field_paths": {"type": "array", "minItems": 1, "items": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}, "description": "Several values in one cell: an array of paths, each an array of segments exactly as `field_path`. The non-empty scalar values are joined with `joiner` in the order given; null, missing, blank text, lists and objects are skipped; when nothing is left the cell shows `empty_text`. Use instead of `field` and `field_path`, never with them."},
          "joiner": {"type": "string", "maxLength": 20, "description": "The text between the values of a `field_paths` column. Default ', '."},
          "empty_text": {"type": "string", "minLength": 1, "maxLength": 80, "description": "Plain text shown in place of a null, missing or empty-string value, with any formatter."},
          "title": {"type": "string", "description": "Column header text."},
          "width": {"type": "integer", "minimum": 20, "maximum": 800},
          "widthGrow": {"type": "integer", "minimum": 1, "maximum": 5},
          "formatter": {
            "type": "string",
            "enum": ["plaintext", "datetime", "tickCross", "tickDash", "ciaLevel", "ellipsisSuffix", "json", "passFailBadge", "conclusionBadge", "toneBadge", "capitalized", "externalLink", "link", "elapsed", "iconMap", "entityType", "baselineRatio", "baselineN", "sparkline", "tailSegment", "painBadge", "arrayCount", "linkList"],
            "description": "Named client-side cell renderer; see Column Formatters below."
          },
          "formatter_params": {"type": "object", "description": "Per-formatter parameters handed to the JS formatter as Tabulator formatterParams; keys are documented per formatter below. `style` applies to every link formatter.", "properties": {"style": {"type": "string", "enum": ["default", "plain"], "description": "Link appearance: `default` is the accent colour, underlined; `plain` is the cell's own text colour with no underline and no hover highlight, still clickable with a focus ring."}, "show": {"type": "string", "enum": ["icon", "name", "both"], "description": "`entityType` only: the type's glyph, its display name as a pill, or both (default)."}, "tone": {"type": "string", "enum": ["good", "bad", "warn", "muted"], "description": "`entityType` only: the name pill's colour; default `muted`."}, "types": false}},
          "tooltip": {"type": "string", "enum": ["full_value"]},
          "header_tooltip": {"type": "string", "maxLength": 600, "description": "Plain-text explanation of the column, shown as the header's pop-over on hover — what the heading means and how to read the cell."},
          "headerSort": {"type": "boolean"},
          "wrap": {"type": "boolean", "description": "true wraps a long text value onto several lines and lets the row grow to fit it, instead of cutting it with an ellipsis. Default false."},
          "align": {"type": "string", "enum": ["left", "center", "right"], "description": "Horizontal alignment of the cell and its heading together, so a value sits under its title. Default left. Every cell is vertically centred whatever this says."}
        }
    }
  }
}
```

`column_mode` options:
- `common_metadata` — fixed column set derived from current entity-spine metadata fields. Canonical entity metadata terminology is `name`, not `display_name` or `title`. This is the only supported mode in V1, and the fallback when no explicit `columns` are given.

#### Column Formatters
A column names its value with exactly one of `field` (a dotted path: `dimensions.dataclass.customer` reads `dimensions` then `dataclass` then `customer`) or `field_path` (an explicit array of segments, each exactly one key whatever it contains: `["dimensions", "dataclass.customer"]` reads the key `dataclass.customer` of `dimensions`; `req-web-stdpanel-table-config-22`). The browser copies a `field_path` value onto each row under a dot-free internal key, so sorting, the quick filter and every formatter read it like any other column. `field_paths` (with `joiner`) puts several values in ONE cell: each item is a `field_path`-style segment array, the non-empty scalar values are joined with `joiner` (default `, `) in the order given, and a row with none shows `empty_text` (`req-web-stdpanel-table-config-28`): the customer and the infrastructure data class become one `high, low` column. `empty_text` is plain text, escaped, shown instead of the cell when its value is null, missing or an empty string, whatever the formatter, so such a cell is never blank; any other value, including `0` and `false`, goes to the formatter (`req-web-stdpanel-table-config-23`).

Every formatter escapes what it renders — a cell value is data, never markup (Tabulator treats a formatter's return as HTML). `columns[].header_tooltip` gives the column a plain-text pop-over on its heading, drawn on the theme's surface and ink in both schemes (`req-web-stdpanel-table-config-24`). `refresh_seconds` makes the table live with a refresh button and a visible interval selector (the Grafana/Kibana shape) — a table that refreshes silently is one the reader cannot trust to be still, and a number that counts down is one the reader cannot stop watching. Pagination applies to every search type: a Gryphon search executes whole and is paged in `execute_search`, which records the pre-page `total_count`, so the footer's "showing N of M" is true for Gryphon-bound tables too (tap#299). `columns[].formatter` selects a named client-side renderer (defined in `panel-table.js`); string names keep the config declarable with no inline JS. Available formatters:
- `plaintext` — raw string value (default), escaped, in a span that ends a long value with an ellipsis.
- `datetime` — local timestamp with zone disclosure, rendered through the shared time-display helper (`spec-web-time-display.md`, `req-web-time-single-helper`). The incoming value is UTC ISO-8601; the formatter localizes to the viewer's browser zone and discloses the zone (`req-web-time-local-display`, `req-web-time-zone-disclosure`).
- `tickCross` — `✓` / `✕` / `–` for true / false / null-or-absent.
- `tickDash` — `✓` for true, a neutral `–` otherwise; for boolean columns where a "no" is unremarkable rather than a fault.
- `ciaLevel` — compact impact level: `low → L`, `moderate → M`, `high → H`, anything else (not-applicable, blank) → a neutral `–`; color-coded by severity.
- `ellipsisSuffix` — last 8 characters with a leading ellipsis; for long opaque identifiers.
- `json` — compact JSON, truncated.
- `capitalized` — the value with its first letter upper-cased and nothing else touched (`stand-up` → `Stand-up`): a closed-set vocabulary word read as a label. Not for identifiers (a branch name, an `owner/name`), whose spelling is the fact.
- `passFailBadge` — `PASS` / `FAIL` pill.
- `conclusionBadge` — GitHub-shaped terminal conclusion pill: `success` green, `failure` / `timed_out` / `startup_failure` red, every other value (`cancelled`, `skipped`, `neutral`, …) a neutral grey, and an absent value a `–` — an empty cell reads as *not observed*, never as quietly fine.
- `externalLink` — an `http(s)` URL rendered as an anchor opening in a new tab (`rel="noopener noreferrer"`), scheme stripped and truncated for display; any non-http(s) value renders as escaped text so a hostile value never becomes a `javascript:` href.
- `link` — the cell's own value as link text; the href comes from `formatter_params.href_field` (another field on the row) or `formatter_params.href_template` (a template over the row, `{data.x}` placeholders URI-encoded per segment so `docs/foo` keeps its slash; any empty placeholder voids the link). Only absolute `http(s)` or same-origin `/` hrefs render, judged on the URL as the browser parses it (so `/<TAB>/host` and `/\host`, which parse protocol-relative, are refused); anything else degrades to text. `external: false` keeps the link in-tab; `text` replaces the cell's value as the link label (a static word such as `history` for a navigation column). A click on the link is the link's alone — the node-mode row click ignores it.
- Page inputs: the panel forwards the page's query parameters to the linked Search as its declared inputs, coerced by the Search's `input_schema` through `tap_grid.search.inputs_from_query` (the one translation point, shared with the graph panel), so `/git-serious/workflow?workflow_id=123` reaches a search that declares `workflow_id` as an integer. Undeclared and paging keys never reach the search.
- `elapsed` — wall-clock between `formatter_params.start` and `formatter_params.end` (ISO timestamps on the row; optional `require_field`: when that field is empty the row has no elapsed yet — an in-flight run's end is whatever the API last touched — and renders `–`, and the row stays out of every baseline and sparkline that shares the params), humanized (`42s`, `1m 07s`, `2h 05m`) with exact seconds in the title; sorts by the computed seconds. Absent or inverted → `–`, never `0s`.
- `baselineRatio` — this row's elapsed over the median of the *other* loaded rows in its group (`formatter_params.baseline`: `group_by` field paths that define comparable rows, e.g. workflow id + trigger; optional `where` field→value filter for the baseline population, e.g. successful runs only; `min_n` default 3; `flag_ratio` default 1.5; `mad_k` default 3): ▲ratio in red when both the ratio and the MAD test flag it slow, ▼ratio muted when unusually fast, a plain ratio otherwise, and `–` with the sample size in the title when fewer than `min_n` comparable rows are loaded — three states, never two. Sorts by the ratio. The population is the rows currently loaded (the page), so the sample size is always disclosed via `baselineN`; a server-side baseline is a search-level derivation once Gryphon has a median.
- `baselineN` — the sample size behind `baselineRatio` (same params): the count of comparable rows loaded, muted when below `min_n`. Sorts numerically.
- `sparkline` — the row's group as an inline SVG strip (`group_by`, `start`, `end`, optional `x` for the mark's time, `color_field` default `data.conclusion`, `bad_values`, `width` 120, `height` 24, optional `href_template`): one bar per loaded row of the group placed at its actual start time on the group's own first→last axis (`axis: "table"` shares one axis across rows for comparable cadence, at the cost of a burst of recent runs piling into a few pixels; the label states the span in days either way), height relative to the group's longest run, failures in the critical hue, this row in the accent, the group median as a hairline; the accessible label and per-bar titles carry the numbers. A cell for a group with no timed rows renders `–`.
- `tailSegment` — the last `/`-separated segment of the value (`owner/repo` → `repo`), full value in the title; `formatter_params.sep` overrides the separator, which may be more than one character (`"__"` turns `aws_core__aws_alb` into `aws_alb`). For a single-account instance the owner is noise on every row.
- `iconMap` — a closed-set value rendered as a glyph: `formatter_params.icons` maps value → same-origin image path, `labels` maps value → accessible label (alt/title; defaults to the value), `show_text` keeps the word beside the glyph. Unmapped values render as text, so a new vocabulary word is visible rather than invisible. TAP ships CI-universal trigger glyphs at `/static/tap_web/icons/trigger-{push,pull-request,schedule,manual,chained,platform}.svg` (Octicon-derived, see the NOTICE there); consumers map their own event vocabulary onto them.
- `entityType` — an entity-type slug (`aws_core__aws_ecs_container`) rendered as the type's own published icon and/or display name, with no map in the page (`req-web-stdpanel-table-config-32`). The server resolves each distinct slug in the column from the entity-type catalog at panel render (the catalog `EntityType` rows the plugin loader writes from each model's `ENTITY_NAME` / `ENTITY_ICON`, the icon through `tap_grid.icon.resolve_icon_url`, the same resolver the viewer panel and graph use) and hands the result to the formatter as `formatter_params.types`, a reserved key the server owns: an author-supplied `types` is refused. The icon address therefore comes only from the registry and never from a row value. `formatter_params.show` is `icon` (the glyph, name as its alt text and title), `name` (the display name as a pill) or `both` (glyph then pill; the default). `formatter_params.tone` (`good` | `bad` | `warn` | `muted`; default `muted`) is the pill's colour: tone is presentation, which a type does not publish. A type with no published icon, or whose icon file is missing, renders without a glyph and never as a broken image; a type with no published name, or one not in the catalog at all, shows a humanised slug (the part after the last `__`, underscores as spaces, each word capitalised); an empty value is a dash. Use one column with `show: icon` and another with `show: name` for the usual icon-then-kind pair. The column names its value with `field` or `field_path`.
- `painBadge` — colored pill for ordinal severity codes.
- `arrayCount` — count of array items, `–` when empty.
- `linkList` — a row field that is a LIST of structured items (for example `[{"id": "c-1", "name": "openssl"}, …]`): each item is its own link on its own line, wrapped rather than cut. `formatter_params.href_template` fills from the ITEM (`{id}`-style placeholders, each value URL-encoded as one component; an item missing a placeholder value has no link); `formatter_params.label_field` (default `name`) is the link text; `external: false` keeps links in-tab (the default opens a new tab, as `link`); `max_items` shows the first N and a `+N more` line whose tooltip lists the rest. A link renders only for an absolute `http(s)` or same-origin `/` href judged on the URL as the browser parses it (the `link` rule); an item with no usable href, and a bare string item, render as text; an item with no label is dropped. An empty or absent list is a dash, never an empty cell. The column sorts by its first label (case-insensitive), then by item count, with empty lists last; the quick filter matches an item's label, never `[object Object]`. The list reaches the browser because a projection row is a plain dict: a module Search row (`req-grid-search-module`) or a Gryphon `RETURN x.data.<json>.<list> AS alias` carries it whole.
- `toneBadge` — a closed-set value as a coloured pill: `formatter_params.tones` maps value → `good` (green) | `bad` (red) | `warn` (amber) | `muted` (grey), the `conclusionBadge` palette; `formatter_params.labels` maps value → display text. A value with no tone renders as plain text — an unlisted state must not borrow a colour — and an empty value is a dash, never quietly fine. The generic form of `conclusionBadge` for any vocabulary (`observed` / `unobservable`, a criticality scale). `capitalize: true` upper-cases the first letter of a value shown without a `labels` entry.
- `toneThreshold` — a NUMBER as a toned pill chosen by thresholds (a CVSS score): `formatter_params.steps` is a list of `{min, tone}`, tried highest `min` first, and the first step whose `min` is at or below the value gives the tone; `zero_tone` is the tone of exactly zero, taken instead of any step; `decimals` (0 to 6) fixes the places shown. Tones are the `toneBadge` palette (`good`, `warn`, `bad`, `muted`; `info` and `neutral` are aliases of the muted grey, so no tone adds a colour). The pill is self-coloured (background and text together), so it reads in the light and the dark scheme, and its tooltip names the tone. A number below every step is plain text, an empty value is a dash, and a non-number is shown as written.
- `percent` — a fraction from 0 to 1 as a percentage (`0.0004` is `0.04%`), `formatter_params.decimals` places (0 to 6, default 2); the raw value is the tooltip. A value outside 0 to 1 or not a number is shown as written, an empty one is a dash.
- `link` with `formatter_params.value_href_template` — an identifier link built from the cell's own value when neither `href_field` nor `href_template` is given: `{value}` is the value (URL-encoded) and `{number}` the first run of digits in it, so `https://cwe.mitre.org/data/definitions/{number}.html` turns `CWE-79` into a link to definition 79. A template naming any other placeholder, or a `{number}` with no digits to fill it, voids the link (the text shows); the same http(s) / same-origin rule applies.

Links are **visible**: every anchor the table renders (`link`, `externalLink`, `linkList` items; class `tap-cell-link`, styled in `tabulator-minimal.css`) draws in the accent link colour with an underline, thickens and darkens on hover, and shows a focus ring on keyboard focus, so a reader can tell a CVE id or a component name is clickable; `externalLink`'s arrow says it leaves the site. A row that navigates through `row_url_template` carries `tap-row--clickable`: a pointer cursor and a hover wash. The colours are `--tap-table-*` tokens on the table root, measured at least 4.5:1 against the row surface; a table with no links and no `row_url_template` is unchanged. `formatter_params.style: "plain"` on a link column opts that column out of the colour, the underline and the hover highlight (`req-web-stdpanel-table-config-26`): for an identifier column where the whole row is the target, the text reads as plain text while the anchor, its focus ring and the row wash stay.

`columns[].wrap: true` lets a text column wrap: a long value (the plain-text cell, and every formatter that renders through it) flows onto as many lines as it needs and the row grows to fit, where the default cuts it with an ellipsis. Long unbroken words break rather than overflow the cell. The value is still escaped text, and sorting and filtering are unchanged (`req-web-stdpanel-table-config-31`).

#### Cell Alignment

Every cell is **vertically centred** and **left-aligned** by default, so a one-line identifier (a CVE id, a badge) sits on the midline of a row that a multi-line `linkList` cell makes tall (`req-web-stdpanel-table-config-25`). `align` changes the horizontal placement only. The stat-card table line and the graph info-window table follow the same rule.

#### Striped Rows

`striped: true` is the alternating-row look: a subtle stripe on every even row from the `--tap-table-stripe` / `--tap-table-stripe-hover` tokens in `theme.css` (light and dark values, so no colour is a literal; `req-web-stdpanel-table-config-27`). It is a panel-level option and is off by default.

#### Rows Selector And Empty Table

The Rows selector lists the page-size steps below the row count and, by default, an `All (N)` entry. `show_all_rows: false` drops the `All` entry for a table that must stay paged (`req-web-stdpanel-table-config-29`): a request for `page_size=0`, or a stored `All` choice, falls back to `default_page_size`, and when no step is below the row count the selector is not drawn. A table-level `empty_text` (1..200 characters, plain text, escaped) is what the table says when it has no rows, in place of the generic `No results.`; it is distinct from a column's `empty_text`, which fills a single empty cell (`req-web-stdpanel-table-config-30`).

#### Chrome

`chrome: minimal` draws no nav bars and no quick filter — the heading, the refresh status and the table alone. For a table that is one row of facts (a repository's identity row) rather than a list to page through; `full` (the default) is unchanged.

#### Column Groups

A `columns[]` item may be a group — `{"title": …, "columns": [ …leaf columns… ]}`, no `field` — rendered as Tabulator's grouped header: the title as a quiet caption over its leaves. One level deep; a group of groups is rejected by the schema, as is an item that is both a leaf and a group.

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
| req-web-stdpanel-table-config-5 | Minimal Chrome | Implemented | `chrome: minimal` renders no nav bar above or below and no quick filter; the heading and refresh status remain; `full` and absent behave as before. | tap#356. Template-rendered; tested. |
| req-web-stdpanel-table-config-6 | Column Groups | Implemented | A `columns[]` item of the form `{title, columns}` validates and renders as a grouped header over its leaf columns; a group nests no further and an item cannot be both leaf and group. | tap#356. Schema `$defs`. |
| req-web-stdpanel-table-config-7 | Tone Badge | Implemented | `toneBadge` maps a closed set of values to good / bad / warn / muted pills through `formatter_params.tones`; an unlisted value is plain text and an empty one a dash. | tap#356. |
| req-web-stdpanel-table-config-8 | Quiet Links | Deprecated | Superseded by `req-web-stdpanel-table-config-16`: links are no longer quiet. | tap#356; reversed because a CVE id or component name was not seen to be clickable. |
| req-web-stdpanel-table-config-9 | Align And Capitalize | Implemented | `columns[].align` (left / center / right) places a cell and its heading together; `capitalized` upper-cases a value's first letter, and `toneBadge` does the same under `capitalize: true` — a closed-set word read as a label, never an identifier. | git-serious-tap#63: the one-row identity table reads label-over-value. |
| req-web-stdpanel-table-config-10 | Initial Sort | Implemented | `initial_sort` is an ordered, non-empty list of `{field, dir}` keys (`dir` is `asc` or `desc`, default `desc`); the table applies it when it first renders, primary key first, and an unknown key or direction is rejected at save time. | The consumer's config says what a table opens sorted by; the user can still re-sort from any header. |
| req-web-stdpanel-table-config-11 | Named Sorters | Implemented | `columns[].sorter` names how a column's values compare; `severityRank` orders severity words (critical, high, medium, low, with error, warning, note and info mapped alongside) by rank and not alphabetically, and an unknown word ranks last. | A closed set; further sorters are added here, never as inline code in a panel's config. |
| req-web-stdpanel-table-config-12 | Link List Formatter | Implemented | `linkList` renders each item of a list-of-structured-items field as its own link on its own line (`href_template` filled from the item, `label_field`, `external`, `max_items`); only a same-origin or http(s) href links, an item with no usable href or a bare string is text, an item with no label is dropped; everything is escaped. | Proven in a real browser: N links, N lines, the filled hrefs. `linkList` is in the formatter enum. |
| req-web-stdpanel-table-config-13 | List Field Reaches The Payload | Implemented | A projection row field that is a list of dicts reaches the embedded payload whole, through the real Search and panel endpoint. | Through the real panel endpoint and a real Gryphon search. |
| req-web-stdpanel-table-config-14 | Link List Sort And Filter | Implemented | A `linkList` column sorts by first label then item count (empty last), and the quick filter matches item labels. | Proven in a real browser. |
| req-web-stdpanel-table-config-15 | Link List Empty | Implemented | An empty or absent list renders a dash, not an empty cell. | Proven in a real browser. |
| req-web-stdpanel-table-config-16 | Link Affordance | Implemented | An anchor rendered by the table (`link`, `externalLink`, `linkList` item, icon link) draws in the accent token `--tap-table-link` with an underline, darkens to `--tap-table-link-hover` on hover, and shows a 2px focus ring on `:focus-visible`; no inline colour on the anchor. | Stylesheet rules on `tap-cell-link`; the formatters emit the class. |
| req-web-stdpanel-table-config-17 | Clickable Row Affordance | Implemented | A raw-mode row whose `_url` is usable (from `row_url_template`) gets the class `tap-row--clickable` (pointer cursor, `--tap-table-row-link-hover` wash) and no inline style; a row without a usable `_url`, and a table with no `row_url_template`, gets neither. | Class added in the row formatter; node-mode rows unchanged. |
| req-web-stdpanel-table-config-18 | Link Token Contrast | Implemented | The link, link-hover and link-on-row-hover colours each reach 4.5:1 against the row surface they sit on (#fff, and the row hover wash). | Computed by a test from the stylesheet's token values. |
| req-web-stdpanel-table-config-19 | Tone Threshold Formatter | Implemented | `toneThreshold` is a known formatter; it tones a number by `formatter_params.steps` (highest `min` first) and `zero_tone`, with the `toneBadge` palette, and shows a below-every-step number as plain text. | `tap_web/tests/test_table_panel.py`. |
| req-web-stdpanel-table-config-20 | Percent Formatter | Implemented | `percent` is a known formatter that shows a 0..1 fraction as a percentage with `decimals` places (default 2) and any other value as written. | `tap_web/tests/test_table_panel.py`. |
| req-web-stdpanel-table-config-21 | Identifier Link Template | Implemented | `link` accepts `formatter_params.value_href_template` with `{value}` and `{number}`; an unfillable template or an unsafe result degrades to text. | `tap_web/tests/test_table_panel.py`. |
| req-web-stdpanel-table-config-22 | Field Path | Implemented | A column may declare `field_path`, an array of segments, instead of `field` (exactly one of the two, `oneOf`); each segment is one key, so a key containing a dot is reachable, and a `field` column resolves as before. | `tap_web/tests/test_table_panel.py`, `tap_web/tests/js/table_columns.test.mjs`. |
| req-web-stdpanel-table-config-23 | Empty Text | Implemented | A column's `empty_text` (1..80 characters) is shown, plain and escaped, for a null, missing or empty-string value with every formatter; zero and `false` are values and use the formatter. | `tap_web/tests/test_table_panel.py`, `tap_web/tests/js/table_columns.test.mjs`. |
| req-web-stdpanel-table-config-24 | Themed Popover | Implemented | The pop-over a `header_tooltip` (or any Tabulator tooltip or popup) opens takes its background, text and border from palette tokens (`--tap-white`, `--tap-slate-900`, `--tap-slate-400`), so it is a themed surface in the light and the dark scheme and not the library's flat white; the sortable-header hover is a token wash, not the library grey. | `tap_web/tests/test_table_polish.py`; measured in a real browser in both schemes (the pop-over text is at least 4.5:1 on its surface). |
| req-web-stdpanel-table-config-25 | Cell Alignment | Implemented | With no config, every table cell (custom, common-metadata and edge columns, grouped leaves) is vertically centred and left-aligned: the column gets Tabulator's `vertAlign: "middle"` and `hozAlign: "left"` unless `align` says otherwise; plain text sits in a shrinkable `tap-cell-text` span so a long value still ends in an ellipsis. The stat-card table line and the info-window table centre their cells vertically too. | `tap_web/tests/test_table_polish.py`, `tap_web/tests/js/table_columns.test.mjs`; measured in a real browser (a tall linkList row keeps the CVE and the badge on its midline). |
| req-web-stdpanel-table-config-26 | Plain Links | Implemented | `formatter_params.style` (`default` or `plain`) applies to `link`, `externalLink` and `linkList`: `plain` adds `tap-cell-link--plain`, which draws the anchor in the cell's own text colour with no underline and no hover highlight, yet it remains an anchor (clickable, with the `:focus-visible` ring, and the row's clickable wash is untouched). Absent or `default` is exactly `req-web-stdpanel-table-config-16`. | `tap_web/tests/test_table_polish.py`, `tap_web/tests/js/table_columns.test.mjs`; measured in a real browser in both schemes. |
| req-web-stdpanel-table-config-27 | Striped Rows | Implemented | `striped: true` puts `tap-table--striped` on the table mount: every even row is drawn on `--tap-table-stripe` and a hovered row on `--tap-table-stripe-hover` (theme tokens with light and dark values; group bands are not striped, a clickable row keeps its own hover wash). Absent or `false`: uniform rows. Text, secondary text and links reach 4.5:1 on both stripe tokens in both schemes. | `tap_web/tests/test_table_polish.py`, `tap_web/tests/test_table_panel.py`; measured in a real browser in both schemes. |
| req-web-stdpanel-table-config-28 | Joined Field Paths | Implemented | A column may declare `field_paths` (an array of path-segment arrays, the `field_path` reading, own keys only) with an optional `joiner` (default `, `) instead of `field` or `field_path` (exactly one of the three; `joiner` only with `field_paths`): the non-empty scalar values are joined in the order given, null, missing, blank, list and object values are skipped, and when none is left the cell is empty so `empty_text` applies. The joined text is what the column sorts, filters and formats by. | `tap_web/tests/test_table_panel.py`, `tap_web/tests/js/table_columns.test.mjs`; measured in a real browser. |
| req-web-stdpanel-table-config-29 | Optional All Rows | Implemented | `show_all_rows` (boolean, default true) set to false leaves the `All` entry out of the Rows selector, ignores `page_size=0` in favour of `default_page_size`, and draws no selector when no step is below the row count; unset or true behaves as before. | `tap_web/tests/test_table_panel.py`. |
| req-web-stdpanel-table-config-30 | Table Empty Text | Implemented | A table-level `empty_text` (string, 1..200 characters) replaces the generic `No results.` when the table has no rows: the server puts it on the mount as `data-tap-table-empty-text` (escaped) and the client escapes it into the Tabulator placeholder; absent, the generic message stays. | `tap_web/tests/test_table_panel.py`, `tap_web/tests/test_table_polish.py`; proven in a real browser. |
| req-web-stdpanel-table-config-31 | Wrapping Text Column | Implemented | A column's `wrap` (boolean, default false) set to true puts the class `tap-col-wrap` on the column's cells: its plain text wraps onto several lines (long unbroken words break rather than overflow) and the row grows to fit, instead of being cut with an ellipsis; the text stays escaped, and sorting, `headerFilter` and the quick filter read the value as before. Absent or false is unchanged. | `tap_web/tests/test_table_panel.py`, `tap_web/tests/test_table_polish.py`, `tap_web/tests/js/table_columns.test.mjs`; measured in a real browser in both schemes. |
| req-web-stdpanel-table-config-32 | Entity Type Formatter | Implemented | A column with `formatter: entityType` shows an entity-type slug as the type's published icon and display name. (1) At panel render the server resolves the distinct slugs of the column from the entity-type catalog (name, and icon URL through `tap_grid.icon.resolve_icon_url`) and passes them as `formatter_params.types`; the page ships no per-type map. (2) `formatter_params.show` is `icon`, `name` or `both` (default `both`) and `formatter_params.tone` is `good`, `bad`, `warn` or `muted` (default `muted`); any other value is refused at config validation. (3) A type with an icon and a name renders both; a type with a name only renders the pill with no image; a slug unknown to the catalog, or a type with no published name, renders a humanised slug, never a broken image or a blank. (4) The icon source is the catalog alone: `types` in an author's `formatter_params` is refused at config validation, a row value is never used as an image address, and the name is escaped. (5) An empty value is a dash, or the column's `empty_text`. | `tap_web/tests/test_table_panel.py`, `tap_web/tests/js/table_columns.test.mjs`. |

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
- V1 Table Panel consumes node results, and projection rows under [Projection Rows](#projection-rows).
- In node mode, rows are derived from the `nodes` members of the canonical search result envelope.
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
| req-web-stdpanel-table-columns-1 | Nodes Only In V1 | Proposed | The initial Table Panel standard displays node search results (and projection rows, `req-web-stdpanel-table-rows`) and does not yet define edge-table rendering. | Projection rows added by tap#432. |
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

### Projection Rows
----
RID: `req-web-stdpanel-table-rows`

Status: `Implemented`

A Gryphon search that projects (`MATCH (a)-[e]->(b) RETURN a.name AS app, e.data.properties.scope AS scope, …`) answers with `rows` and zero `nodes` (`req-grid-gryphon-rows`). The table renders those rows, so a table whose row is a join (an assignment, a rule with its policy, a run with its workflow) is one standard table, not a custom panel (tap#432, tap#297).

#### Status Details
Before this requirement the panel read only `nodes`, and a projection-bound table rendered "No results" silently while its search returned rows.

#### Implementation
- **Mode follows the envelope.** When the envelope has non-empty `rows` and no `nodes`, the panel is in projection mode; every other envelope (nodes present, or both empty) is node mode, rendered exactly as before. An empty projection therefore renders the node-mode empty table with a total of 0, which is true.
- **Payload.** The rows are the embedded data payload, and the mount carries `data-tap-table-mode="raw"`: `panel-table.js` renders flat row dicts, does no object-viewer navigation, and a row with a `_url` becomes a click target (only absolute `http(s)` or same-origin paths navigate; a click on an in-cell link stays the link's).
- **Columns.** `columns[]` applies unchanged, with each `field` naming a RETURN alias, so formatters (`toneBadge`, `link` with an `href_template` of `{alias}` placeholders, `datetime`, …), `header_tooltip`, `quick_filter` and `height` work as in node mode. With no `columns` declared, there is one column per alias in RETURN order, titled by the alias.
- **Paging and the total.** `execute_search` pages only the node or edge side, and a Gryphon search executes whole, so the envelope's `rows` is the complete result. The panel pages it by the same window (`limit` from the paginated envelope, which honours `max_limit`; `offset` from the request), and `total_count` is the length of the full row set. The envelope's own `info.total_count` counts nodes (0 for a projection) and is never shown as the row total.
- **Row links.** `row_url_template` (config) is filled per row into `_url`: each `{alias}` placeholder takes that row's value, URL-encoded as a single component, and a placeholder with no value (absent, null or empty) leaves the row without a link. The schema admits only a same-origin path: it starts `/`, is not `//…` or `/\…`, and holds no whitespace, control character or backslash anywhere, because a browser strips tab/CR/LF and reads a backslash as `/` while parsing, which would turn `/<TAB>/host` into `//host`; the pattern ends in `(?![\s\S])`, a true end of string, because `$` also matches before a trailing newline. The same pattern is checked again where the template is used, because only the editor's save validates config against the schema and a grift-seeded config arrives unvalidated; a template that fails it links no row. Only the template sets `_url`: a projection that RETURNs `… AS _url` has that alias dropped from every row, so a search cannot hand the client a link the template's same-origin rule never saw. Rows are copied, never mutated.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-stdpanel-table-rows-1 | Projection Rows Render | Implemented | A table bound to a Gryphon search that RETURNs aliases embeds the search's rows as its payload and marks its mount `data-tap-table-mode="raw"`. | Through the real panel endpoint and a real Gryphon search. |
| req-web-stdpanel-table-rows-2 | Aliases Are The Columns | Implemented | Declared `columns[]` are passed through as the column spec; with none declared, the columns are the RETURN aliases in RETURN order, titled by the alias. | |
| req-web-stdpanel-table-rows-3 | Paged With A True Total | Implemented | Projection rows are paged by the panel's window, and the footer's total is the full row count, never the envelope's node-side `total_count`. | tap#299 |
| req-web-stdpanel-table-rows-4 | Node Mode Unchanged | Implemented | An envelope with nodes renders as before: node payload, no mode attribute, the envelope's `total_count`. | Regression guard. |
| req-web-stdpanel-table-rows-5 | Row URL Template | Implemented | `row_url_template` fills each row's `_url` with URL-encoded alias values; a missing value voids that row's link; a `_url` RETURN alias never survives into the payload; a template that is not a same-origin path fails config validation. | |
| req-web-stdpanel-table-rows-6 | One Shared Row-URL Rule | Implemented | The same-origin pattern and the encoded fill behind `row_url_template` are one implementation (`tap_web/panels/row_url.py`) used by the Table panel and the Chart panel's `click`. | Django-free tests of the rule. |

#### Future
- Grouping (`group_by`) over projection rows works on flat aliases today but is untested against a real consumer.
- Row navigation by an `entity_id` alias (to the object viewer) without a template.

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
