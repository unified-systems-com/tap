# Viz Badges Specification

## Philosophy

Viz badges are small attached visual markers rendered on a node to communicate information without consuming the node body. They are a TAP Viz presentation pattern, not a new icon ownership system. Canonical icon ownership remains defined by the grid icon contract. The badges spec defines how TAP Viz may place and group those visual cues on Cytoscape-rendered nodes.

The first useful badge pattern is the type icon badge: a small circular badge anchored to the upper-left corner of a node that reminds the viewer what kind of node they are looking at. This pattern should work the same way for parent nodes and leaf nodes. That consistency keeps the interior of a parent node available for child layout while keeping the interior of a leaf node available for the node name.

Badge sets are the related grouping mechanism for hosting multiple related badges on a single node. The first concrete consumer is the status badge set family — alert, warning, and other named state signals — configured per projection and kept visually distinct from the type icon badge.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Consistent | The same badge concepts should work across parent and leaf nodes. |
| 2. | Non-Intrusive | Badges should preserve the node body for names, children, and other content. |
| 3. | Modular | The badge vocabulary should leave room for future grouped badge constructs without requiring them in the first implementation. |
| 4. | TAP-Owned | Badge behavior should be described by TAP Viz concepts rather than ad hoc Cytoscape-only styling tricks. |
| 5. | Evolvable | Status badge sets begin with a simple population mechanism and reserve an extension point for richer bindings later. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-badges-terminology | [Badge Terminology](#badge-terminology) | Implemented | Defines the vocabulary for badge, type icon badge, and badge set |
| req-viz-badges-type-icon | [Type Icon Badge](#type-icon-badge) | Implemented | Upper-left circular badge that indicates node type |
| req-viz-badges-body-preservation | [Node Body Preservation](#node-body-preservation) | Implemented | Badge placement must preserve the node body for primary content |
| req-viz-badges-badge-set | [Badge Set](#badge-set) | Implemented | Grouped per-node badges rendered in a shared location |
| req-viz-badges-status-sets | [Status Badge Sets](#status-badge-sets) | Implemented | Projection-level `status_badges` config producing alert, warn, and other named node signals |

## Requirements

### Badge Terminology
----
RID: `req-viz-badges-terminology`

Status: `Implemented`

TAP Viz uses a small vocabulary for node-attached markers.

#### Implementation

- A `badge` is a small attached visual marker rendered on or at the edge of a node.
- A `type icon badge` is a badge whose purpose is to show the node's type icon.
- A `badge set` is a grouped collection of related badges rendered together in a shared location on a node.
- A `status badge set` is a badge set for state-style node signals such as information, warning, and alert.

#### Development

Use `badge` as the umbrella term and more specific names for concrete badge purposes. Avoid overloaded terms such as `breadcrumb`, which imply path or hierarchy semantics rather than attached node markers.

#### Future

Add more badge subclasses only when they represent clearly distinct semantics and placement rules.


### Type Icon Badge
----
RID: `req-viz-badges-type-icon`

Status: `Implemented`

Nodes may render a type icon badge: a small circular badge anchored to the upper-left corner that indicates node type for both parent and leaf nodes.

#### Status Details

This is the first canonical badge pattern for TAP Viz. It replaces the need to choose between putting the icon inside the node body or only rendering it beside a custom HTML label.

#### Implementation

- The type icon badge uses the node's canonical type icon from the grid icon contract.
- The type icon badge is rendered as a small circular badge.
- The canonical anchor position is the upper-left corner of the node representation.
- The same type icon badge concept applies to:
  - leaf nodes
  - parent nodes
  - child nodes nested within parent nodes
- Missing type icons must fail safely by omitting the badge rather than making the node unusable.
- Badge rendering is controlled by a projection-wide `node_style` field. When `node_style` is `"icon-badge"`, all nodes in the projection receive badge treatment.
- Badges are implemented as separate Cytoscape nodes (not HTML overlays or background-image layers) so they protrude from the host node body and scale proportionally with zoom.
- Badge nodes are non-interactive (`"events": "no"`) and locked in position.
- All badges at a given elevation share a single uniform diameter. The runtime
  derives that diameter using the "smallest host wins" rule: scan every
  badge-eligible host, take the smallest `Math.min(w, h)`, multiply by the
  badge ratio (default `0.35`), and clamp to a floor of 24 model units. Every
  badge in the scene is then sized to that single value. This prevents large
  containers from producing badges that visually dominate the scene, and keeps
  badges readable even when recursive-scaling collapses leaf hosts in model
  coordinates.
- Badge bubbles render with a fully transparent background and no border by
  default, so the host's type icon reads as a free-floating glyph rather than
  inside a visible frame. A future setting may restore a visible bubble
  (see the Future section).
- The host node's icon is stashed and cleared when badges are applied, and restored on cleanup.
- Badge creation runs after layout completion so host positions and dimensions are stable.
- The runtime module is `tap_viz/static/tap_viz/js/runtime/badge-nodes.js`.

#### Development

The value of the pattern is consistency. A viewer should learn that the upper-left badge is where node identity-by-type lives, regardless of whether the node is acting as a container.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-badges-type-icon-1 | Shared Pattern Across Node Kinds | Implemented | Parent and leaf nodes use the same type icon badge concept. | `applyBadgeNodes` iterates all nodes with `icon_url` regardless of parent/leaf status |
| req-viz-badges-type-icon-2 | Upper-Left Anchor | Implemented | The type icon badge anchor is the node's upper-left corner. | Badge positioned at `(pos.x - w/2, pos.y - h/2)` |
| req-viz-badges-type-icon-3 | Circular Badge Form | Implemented | The type icon badge renders as a small circle. | `node[_is_badge]` style: `shape: "ellipse"` |
| req-viz-badges-type-icon-4 | Grid Icon Contract Reused | Implemented | The badge reuses the canonical node type icon rather than introducing a second icon source. | Badge reads `icon_url` from host node data |
| req-viz-badges-type-icon-5 | Missing Icon Safe Fallback | Implemented | Nodes without an icon remain usable and simply omit the badge. | Filtered by `icon_url` presence check |

#### Future

- Define exact sizing, overlap, and scaling rules once the first implementation is exercised across several layouts.
- Expose badge bubble appearance as a configurable setting (background fill,
  border color, border width) on the projection or on a per-elevation basis
  so layouts that want a visible frame can opt in. Today the fully transparent
  borderless form is hard-coded as the default.
- Consider a per-projection override for the badge sizing rule (e.g. "smallest
  host wins" vs "fixed fraction of viewport") once more layouts exercise the
  current default.


### Node Body Preservation
----
RID: `req-viz-badges-body-preservation`

Status: `Implemented`

Badge placement must preserve the node body for the node's primary content.

#### Implementation

- For parent nodes, the node body should remain available for child node layout.
- For leaf nodes, the node body should remain available for the node's primary text label.
- The type icon badge should not require the icon to be centered in the node body.
- Badge positioning should reduce competition between iconography and primary content.

#### Development

This is the main practical reason for adopting the type icon badge pattern. It lets the type reminder stay visible while leaving the central area available for what the node needs to contain.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-badges-body-preservation-1 | Parent Body Preserved | Implemented | Parent nodes retain usable body space for children. | Badge is a separate node outside host bounds |
| req-viz-badges-body-preservation-2 | Leaf Body Preserved | Implemented | Leaf nodes retain usable body space for their names. | `_badge_active` style centers text label in body |
| req-viz-badges-body-preservation-3 | Icon No Longer Center-Bound | Implemented | The type icon no longer needs to occupy the center of the node body. | Icon moved to external badge node |

#### Future

If TAP later supports richer interior node content, keep badge placement rules biased toward protecting the node body first.


### Badge Set
----
RID: `req-viz-badges-badge-set`

Status: `Implemented`

A badge set is a grouped collection of related badges rendered together in a defined location on a node. The first concrete consumer of this mechanism is the status badge set family described in `req-viz-badges-status-sets`.

#### Implementation

- A node may host zero or more badge sets in addition to its type icon badge.
- For v1, the only supported badge-set anchor is the node's upper-right corner — opposite the type icon badge along the top edge.
- When multiple badge sets are active for a node, their badges render left-to-right along the upper-right edge in the order the sets are declared. Declaration order follows the iteration order of the projection's `status_badges.badge_sets` array. An array is used (rather than a keyed object) because Postgres JSONB does not preserve JSON object key order; arrays do preserve element order.
- Badge sets derive their diameter from the "smallest host wins" uniform rule defined in `req-viz-badges-type-icon`, scaled down by a fixed status-badge ratio (currently `0.75`). The size hierarchy — type icon badges slightly larger than status badges — establishes visual priority so the eye reads identity first, state second.
- Individual badges within a set remain non-interactive in v1 (`"events": "no"`, locked position).
- Badge set rendering runs after layout completion so host positions and dimensions are stable.

#### Development

Keep multi-set rendering rules minimal until a second badge-set family (beyond status) actually ships. The upper-right corner is intentionally the only supported location at this stage — adding other anchors introduces overflow, collision, and ordering questions that are better handled when a concrete second use case arrives.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-badges-badge-set-1 | Upper-Right Anchor | Implemented | Badge sets render in the node's upper-right corner, opposite the type icon badge. | `tap_viz/static/tap_viz/js/runtime/status-badges.js` |
| req-viz-badges-badge-set-2 | Left-To-Right Ordering | Implemented | When a node hosts multiple badge sets, their badges render left-to-right along the upper-right edge in declaration order. | Order source is the `status_badges.badge_sets` array; array chosen because JSONB loses object key order |
| req-viz-badges-badge-set-3 | Scaled Sizing | Implemented | Badges in a set derive their diameter from the type icon badge's uniform size, scaled down by a fixed ratio (currently `0.75`) to establish visual hierarchy. | Type icon uses `computeUniformBadgeSize` in `badge-nodes.js`; status badges multiply by `STATUS_BADGE_RATIO` in `status-badges.js` |
| req-viz-badges-badge-set-4 | Non-Interactive | Implemented | Badges within a set do not respond to mouse events in v1. | `events: "no"` in Cytoscape styles |
| req-viz-badges-badge-set-5 | Post-Layout Rendering | Implemented | Badge sets are applied after the layout pass so positioning uses stable host bounds. | Invoked from `projection.js` after `runLayoutsSerially` |

#### Future

- Additional anchor locations (bottom, left) with overflow and ordering rules once a second use case justifies them.
- Per-set opt-out of the shared sizing rule where specific sets need a distinct scale.
- Count-bearing vs presence-only badges as a formal distinction.
- Click interactivity for opening per-badge detail surfaces.


### Status Badge Sets
----
RID: `req-viz-badges-status-sets`

Status: `Implemented`

Status badge sets surface node-level state signals — alert, warning, and other named families — through per-set badges configured at the projection level. They are the first consumer of the badge set mechanism defined in `req-viz-badges-badge-set`.

#### Status Details

This requirement covers visual rendering, the projection config shape, and a first population mechanism that is sufficient for seed-data testing. On-click behavior, additional population mechanisms (notably search-backed population via the existing JSON search endpoint), and severity-based visual refinements are tracked as Future work.

#### Implementation

Projections gain a top-level `status_badges` object. If the field is absent, or `badge_sets` is empty, no status badges render.

```json
"status_badges": {
  "refresh_seconds": 30,
  "badge_sets": [
    {
      "name": "alert",
      "color": "#ef4444",
      "text_color": "#ffffff",
      "population": {
        "type": "static_by_node_type",
        "rules": [
          {"entity_type": "ec2_instance", "count": 10},
          {"entity_type": "rds_database",  "count": 3}
        ]
      }
    }
  ]
}
```

Config fields:
- `refresh_seconds`: shared refresh cadence for all sets in this iteration. `0` disables automatic refresh.
- `badge_sets`: ordered array of set config objects. Array order determines the left-to-right rendering order defined in `req-viz-badges-badge-set`. An array (rather than a keyed object) is used because Postgres JSONB does not preserve JSON object key order.
- Each set entry:
  - `name` (required): unique identifier for the set within this projection (e.g. `"alert"`, `"warn"`). Used in badge element ids and any future diagnostic logging.
  - `color` (required): badge fill color.
  - `text_color` (optional, default `"#ffffff"`): count label color.
  - `population` (required): object describing how per-node counts are computed.
- `population.type` is the extension point. Supported in v1:
  - `"static_by_node_type"`: each node's count is produced by the first matching entry in `rules`, where a rule matches when the node's `entity_type` equals `rules[i].entity_type`. Nodes with no matching rule produce no badge for that set.

Rendering:
- A status badge renders as a filled circle in the set's `color` with a numeric count label in the set's `text_color`.
- The default border is a thin solid line in a darker related shade of the fill. The shade is computed client-side by multiplying each RGB channel of `color` by a fixed darken factor (currently `0.6` in `status-badges.js`). The tonal rim gives each badge an "enamel pin" quality that harmonizes with a muted palette, rather than the high-contrast outline a cream or white ring would produce. Border color is not separately configurable in v1.
- A badge renders only when its computed count is a positive integer. `0`, missing, or non-numeric values produce no badge for that set on that node.
- The initial paint waits for the first population pass to complete before any status badges appear; there is no pre-render from embedded node data. For `static_by_node_type`, the first pass is a synchronous client-side sweep that runs immediately after layout, so there is no visible delay.
- Rendering uses the badge set mechanism from `req-viz-badges-badge-set` (upper-right anchor, left-to-right order, uniform sizing, non-interactive).

Refresh and stale state:
- When `refresh_seconds` is a positive integer, the client re-runs the population pass on that interval and updates the scene in place: badges appear when a count transitions from zero to positive, disappear on the reverse, and their count labels update when the count changes.
- For `static_by_node_type`, the refresh pass is a data no-op (rules are static), but the refresh hook is still plumbed through so future population types slot in without reshaping the runtime.
- On a failed refresh, all status badges that were rendered from the most recent successful pass switch their border to a dashed grey line to mark stale state. Count labels and fill color are left unchanged.
- On a subsequent successful refresh, borders return to their default solid line in the darkened related shade.

Runtime module:
- The runtime extends `tap_viz/static/tap_viz/js/runtime/badge-nodes.js` so a single post-layout pass handles the type icon badge and each configured status badge set for every eligible host.

Search-backed population (`population.type: "search"`):
- Landed. Each eligible set may specify `population: {type: "search", search_id: "<uuid>", inputs: {...}}`.
- At render time the client POSTs to `POST /api/v1/searches/{search_id}/execute` with the `inputs` payload and reads the aggregating-query `rows` field from the response envelope (enabled by `spec-grid-gryphon-multihop-aggregation.md`).
- Each row is expected to carry `{entity_id, count}`; the client builds a `{entity_id: count}` map and renders badges per-node using the existing sizing/positioning logic.
- Multiple sets with search populations run in parallel (Promise.all); static and search populations coexist on the same projection.
- Fetch failures engage the stale-border marker (`req-viz-badges-status-sets-7`) without clearing the previously rendered counts, so the scene stays informative when the backend is momentarily unreachable.

#### Development

The `population.type` value is the primary extension axis. Adding a new population type should not require changing the `status_badges` shape, the rendering code, or the refresh plumbing — only the population dispatcher. Keep each population implementation small and pure: inputs are the current scene's nodes plus the set's config; output is a map of `node_id -> count`.

Only one status set (typically `alert`) is expected in the first seed demo. The config supports multiple sets from day one so seed data and later panels can exercise the multi-set rendering path without a schema change. Colors, text colors, and population rules are entirely projection-owned — the spec does not fix a canonical palette for any set name.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-badges-status-sets-1 | Projection Field Shape | Implemented | Projections accept a `status_badges` object containing `refresh_seconds` and an ordered `badge_sets` array. | Schema enforced via `_PROJECTION_DEFINITION_SCHEMA` in `tap_viz/models.py` |
| req-viz-badges-status-sets-2 | Per-Set Color Config | Implemented | Each set declares its own `color` and optional `text_color`. | Applied via `_status_fill` / `_status_text` data attributes on badge nodes |
| req-viz-badges-status-sets-3 | Static Population Supported | Implemented | `population.type: "static_by_node_type"` computes per-node counts from an ordered list of `{entity_type, count}` rules, first match wins. | `_runPopulation` in `status-badges.js` |
| req-viz-badges-status-sets-4 | Positive Count Required | Implemented | A set's badge renders only when its computed count is a positive integer; `0`, missing, or non-numeric produces no badge for that set on that node. | |
| req-viz-badges-status-sets-5 | Wait For First Pass | Implemented | No status badges render until the first population pass completes. | Render pass runs post-layout before badges are visible |
| req-viz-badges-status-sets-6 | Periodic Refresh Plumbed | Implemented | When `refresh_seconds > 0`, the population pass re-runs on that interval and updates badges in place (appear, disappear, update label). | `setInterval` hook in `applyStatusBadges`; refresh is a data no-op for static populations but the hook is active |
| req-viz-badges-status-sets-7 | Stale Border On Failure | Implemented | On a failed refresh, rendered status badges switch to a dashed grey border. The default solid border in the set's color returns on a subsequent successful refresh. | `_setStale` stamps `_status_stale` data attribute; CSS selector applies dashed grey border |
| req-viz-badges-status-sets-8 | Uses Badge Set Mechanism | Implemented | Status badges render via the upper-right anchor, left-to-right order, uniform sizing, and non-interactive behavior defined in `req-viz-badges-badge-set`. | |
| req-viz-badges-status-sets-9 | Empty Config Is Safe | Implemented | Absent `status_badges` or empty `badge_sets` renders no status badges and does not error. | Guarded in `applyStatusBadges` entry point |
| req-viz-badges-status-sets-10 | Independent Of `node_style` | Implemented | Status badges render independent of the projection's `node_style` setting; they do not require `"icon-badge"` mode. | `projection.js` applies status badges unconditionally when configured |

#### Future

- **Click behavior**: open an alert summary popup or side panel on click, with links to individual alert detail pages.
- **Elevation-level status badge overrides**: allow per-elevation `status_badges` that override the projection-level default. Projection-level is sufficient for v1 demos but narrower scenes would benefit from different counts at different zoom levels.
- **Per-set refresh cadence**: allow individual sets to override the top-level `refresh_seconds` when different population mechanisms need different cadences.
- **Severity-aware rendering**: beyond color-per-set, shape or emphasis variations based on count thresholds.
- **Count overflow presentation** (e.g. `99+`) once real data exercises the limits of a small badge.
- **Per-set stale markers** if partial-failure scenarios (some sets stale while others succeed) become common.
- **Accessibility**: tooltip or ARIA label announcing the count and set name once click behavior lands.
- **Configurable border treatment**: today the rim is a darkened related shade computed at a fixed factor. A per-set `border_color` override (or named rim styles like `"tonal"`, `"cream"`, `"contrast"`) would let designers pick between the current embossed look and a sticker-applied look.
- **Depth cues (shadows)**: an early iteration tried Cytoscape `underlay-*` and `ghost` for directional drop shadows. Both were rejected — underlay reads as a symmetric glow, ghost reads as a double-exposure at badge scale. Worth revisiting if a proper Gaussian-blur shadow primitive becomes available, or via a selective per-entity-type configuration that enables shadows only where they improve readability.
