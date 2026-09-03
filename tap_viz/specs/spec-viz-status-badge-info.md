# Viz Status Badge Info Window Specification

## Philosophy

Status badges advertise that *something* is there — a count of findings, warnings, or other signals — but the number alone is not the answer. The info window is the paired disclosure surface: clicking a badge (or the host it sits on) opens a panel that names the underlying rows.

The info window is deliberately narrow in scope for v0. It is a read-only listing, not a remediation surface. It reuses the TAP Search system for data, does not introduce a new service, and does not bring in a third-party popover library. It is the discoverability half of the status badge feature, and nothing more.

Click semantics are part of this story. TAP Viz previously navigated to the object viewer on any node tap, a behavior that conflicts with the info window trigger and which the status badge feature now supersedes. Click semantics are formalized in [spec-viz-panel.md](spec-viz-panel.md); this spec assumes that formalization and focuses on the info window itself.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Discoverable | Opening the window is a natural single-click action on either the badge or its host. |
| 2. | Accurate | The rows displayed come from the same Search system that drives the counts, so the count and the list cannot drift. |
| 3. | Non-Intrusive | The window is a small overlay that does not hijack the graph, obscure navigation chrome, or block the panel. |
| 4. | Dismissable | Close via X button, ESC key, or click-outside. Any of the three must restore the graph to its pre-click interaction state. |
| 5. | Framework-Free | The window is a plain HTML overlay positioned from Cytoscape coordinates. No popper, floating-ui, or other library. |
| 6. | Evolvable | The v0 surface shows only a name column. Columns, row actions, and pan-zoom-to-instance are explicit future extensions with reserved config shape. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-info-window-trigger | [Trigger Surface](#trigger-surface) | Implemented | Single click on badge or badged host opens the window |
| req-viz-info-window-config | [Info Window Configuration](#info-window-configuration) | Implemented | Per-badge-set `info_window` block referencing a Search |
| req-viz-info-window-contents | [Window Contents](#window-contents) | Implemented | Sections per badge set, name column only in v0 |
| req-viz-info-window-rendering | [Window Rendering](#window-rendering) | Implemented | Plain HTML overlay, positioned from host screen coords |
| req-viz-info-window-dismissal | [Dismissal](#dismissal) | Implemented | X button, ESC key, and click-outside all dismiss |
| req-viz-info-window-lifecycle | [Data Lifecycle](#data-lifecycle) | Implemented | Fetch on open, loading/empty/error states, no caching in v0 |
| req-viz-info-window-pan-zoom | [Pan-Zoom to Instance](#pan-zoom-to-instance) | Backlog | Zoom to host on open, restore on close — deferred past v0 |

## Requirements

### Trigger Surface
----
RID: `req-viz-info-window-trigger`

Status: `Implemented`

The info window opens on a single click on a status badge. Host-body taps no longer trigger the info window — that gesture is reserved for plugins/projections to claim per entity type.

#### Implementation

- A single click on any status badge (`[_is_status_badge]`) opens the info window for that badge's host. The clicked set does not take precedence in v0 — the window shows sections for every badge set configured with an `info_window` block, not just the one that was clicked.
- Host-body single-tap is **not** a trigger. The earlier "single click on a badged host opens the info window" rule was removed in the badge-only-trigger refactor — it conflicted with plugin-owned host-tap actions. See [spec-viz-panel.md](spec-viz-panel.md) `req-viz-panel-click-semantics-2` (Deprecated) and `req-viz-panel-click-semantics-7` (Implemented).
- A single click on any host that does not have a status badge does nothing (default Cytoscape selection applies; no navigation, no window).
- Clicking any badge on a host whose info window is already open closes the window. Reopening on a different host closes the current one and opens a new one.
- Only one info window is open at a time per panel.

#### Development

- The previously-implemented "click to navigate to object viewer" behavior is removed. That removal is formalized in [spec-viz-panel.md](spec-viz-panel.md) (`req-viz-panel-node-nav` → `Deprecated`, superseded by a new `req-viz-panel-click-semantics`).
- Double-click semantics (elevation transition for projection panels) are preserved and unchanged.
- Badge-tap fires immediately (no debounce). The host-tap debounce machinery is retained only to drive double-tap detection.

#### Future

- A config flag on the badge set could eventually make the window show only the clicked set's rows rather than all sets. v0 does not implement this.

### Info Window Configuration
----
RID: `req-viz-info-window-config`

Status: `Implemented`

Info window data binding is declared per badge set inside the projection's `status_badges` block.

#### Implementation

- A badge set may include an optional `info_window` object. When present, the window shows a section for that badge set. When absent, the set contributes no section.
- `info_window.search_id` (required when `info_window` is present) is the UUID of a TAP Search entity. The search must return rows that include `entity_id` and `name` fields. Additional fields are ignored in v0.
- `info_window.inputs` (optional, default `{}`) is a static JSON object passed verbatim as the search's `inputs` parameter at fetch time.
- Rows are grouped client-side by `entity_id`. When the info window opens for host `H`, only rows where `entity_id === H` are displayed in that section.
- The search is run on each window-open, not cached. Refresh behavior is defined under [Data Lifecycle](#data-lifecycle).
- The projection definition schema in `tap_viz/models.py` (`_PROJECTION_DEFINITION_SCHEMA`) gains optional `info_window` inside `badge_sets` items, with the shape above. Schema validation rejects a badge set that declares `info_window` without a `search_id`.

#### Development

- Reusing the Search system means the same query can drive the count and the list: the count search returns aggregate rows, the info search returns detail rows. Separate searches, one responsibility each. No new service layer.
- Picking a name field over "title" matches the finding model (`Finding.name`) and most other TAP entity types.

#### Future

- A column config (e.g. `info_window.columns: [{field, label}]`) will drive which row fields render beyond name. v0 hardcodes name.
- An input-templating mechanism (e.g. `inputs: {host_entity_id: "{{host.entity_id}}"}`) would let the search filter server-side by host rather than returning rows for every host and filtering client-side. v0 prefers the simpler always-full-dataset approach since the count search already returns one row per host.
- A `detail` variant that does not require a matching badge population could support "info-on-click without a count badge", but that's outside v0 scope.

### Window Contents
----
RID: `req-viz-info-window-contents`

Status: `Implemented`

The info window displays sections grouped by badge set, each listing the rows that belong to the clicked host.

#### Implementation

- The window header shows the host's display name (from `node.data("name")`) and a small entity type label.
- Each badge set with an `info_window` config that returned at least one row for this host becomes one section.
- A section has a colored indicator (matching `badge_set.color`), the badge set name as a label, and a count (number of rows for this host in this set).
- Section body is a table with one column: `Name`, populated from the row's `name` field. Rows are listed in the order returned by the search.
- A section with zero rows for this host is omitted (not shown as "0 findings"). If every section would be empty, the window is not opened at all (silent no-op) — this only happens if the count went stale and the click came in between refreshes.
- A badge set without an `info_window` block contributes no section, even when the host has an active badge for that set.

#### Development

- Keeping the section-empty case silent avoids showing a window with "nothing to show" as the result of a click. If the click target truly has no info content, the click does nothing.
- The v0 name-only column keeps the surface testable and cheap. Expanding to richer columns is a config change later, not a rewrite.

#### Future

- Row click opens the TAP object viewer for that row's entity. v0 row is static text.
- Pagination or virtualization for high-row-count sections.
- A "view all" link that drops the user into the full search result grid.

### Window Rendering
----
RID: `req-viz-info-window-rendering`

Status: `Implemented`

The info window is a plain HTML overlay inside the viz panel, positioned relative to the host's rendered Cytoscape screen coordinates.

#### Implementation

- The window is a single `<div>` appended to the panel container (not a cytoscape node). It is created on open and removed on close — not a persistent hidden element.
- Positioning: anchor the window's upper-left corner to the host's upper-right rendered position plus a small offset, clamped to the panel viewport so the window stays fully visible.
- Width is fixed (e.g. 280px for v0). Height grows with content up to a max-height (e.g. 60% of panel height), with internal scroll past that.
- The window does not follow the node on pan/zoom. If the user pans or zooms while the window is open, the window stays at its open-time position. This keeps rendering simple and avoids thrash on every Cytoscape frame.
- z-index places the window above the Cytoscape canvas but below any global modal overlay.
- Styling lives in `tap_viz/static/tap_viz/css/` and uses a CSS class namespace (e.g. `tap-viz-info-window`). No inline style tokens beyond coordinate positioning.

#### Development

- Rolling our own avoids a library dependency and the past reliability issues with `cytoscape-popper`. The positioning math is a small amount of code because we already do the same work in `status-badges.js` to place badges.
- Not following the node during pan/zoom is a deliberate v0 simplification. It pairs naturally with the "click-outside dismisses" rule (see below): if the user wants to move around the graph, they can dismiss the window and reopen it.

#### Future

- Anchored-follow mode (window tracks host position during pan/zoom). Would require a Cytoscape `render` or `viewport` event listener and per-frame position recomputation.
- Viewport-edge flip (open left-of-host when upper-right would clip). v0 clamps to viewport rather than flips.

### Dismissal
----
RID: `req-viz-info-window-dismissal`

Status: `Implemented`

Any of three user actions must close an open info window.

#### Implementation

- **X button**: a small close affordance in the window header. Click dismisses.
- **ESC key**: a document-level keydown listener attached on open, removed on close. Pressing ESC dismisses.
- **Click-outside**: a document-level click listener attached on open, removed on close. A click whose target is outside the window element dismisses. Clicks on the originating host or badge also dismiss (which, combined with the trigger rule, makes badge-click a toggle).
- On close, the window element is removed from the DOM and the document-level listeners are detached.
- Closing the panel, switching elevations, or navigating away must dismiss cleanly — any info window open at teardown is removed.

#### Development

- Three dismissal paths might feel redundant, but each maps to a user intent: X is explicit dismissal, ESC is keyboard-first, click-outside is graph-exploration flow.

### Data Lifecycle
----
RID: `req-viz-info-window-lifecycle`

Status: `Implemented`

Data fetching, loading, empty, and error states.

#### Implementation

- On open, the window renders immediately with a loading indicator per section.
- For each badge set with an `info_window` config, a POST to `/api/v1/searches/{search_id}/execute` with the configured `inputs` is issued. Fetches for multiple sets run in parallel.
- On success, rows for the clicked host are rendered in the section. The other sets' sections render as their fetches resolve, independently.
- On fetch error for a section, that section shows an error row (e.g. "failed to load"). Other sections are not affected.
- An empty result for a host in a given section omits the section entirely (see [Window Contents](#window-contents)).
- If every section fails, the window shows a single error message in the body and is still dismissable.
- No caching in v0. Reopening the window refetches. This matches the count-refresh policy: badge counts already refresh at `status_badges.refresh_seconds`, and the info window is paired with that cadence by virtue of always fetching fresh.

#### Development

- No cache keeps the implementation tight and avoids stale-row bugs for v0. The dataset is small (one request per badge set per open).
- The status badge code already reads rows with an `entity_id` key and parses with the same envelope; the info window reuses that API contract directly.

#### Future

- Short-lived caching tied to badge refresh cadence would avoid refetch on rapid open-close-open.
- Client-side filtering when the search returns ALL hosts' rows can be replaced by server-side filtering once input-templating lands (see [Info Window Configuration](#info-window-configuration) Future).

### Pan-Zoom to Instance
----
RID: `req-viz-info-window-pan-zoom`

Status: `Backlog`

On window open, the graph pans and zooms to center the host at a comfortable zoom level. On close, the graph restores the pre-open pan and zoom.

#### Status Details

Deferred out of v0. The window behavior itself is worth validating first before wiring viewport animation on top. Design notes preserved here so the follow-up implementation has a clear starting point.

#### Implementation (planned)

- On window open: capture `cy.pan()` and `cy.zoom()`. Animate to a target that centers the host's bounding box, with a zoom level that fits the host plus a margin, clamped to sensible min/max. Animation duration ~300ms.
- On window close (via any dismissal path): animate back to the captured pan and zoom. Restoration fires even if the user has manually panned or zoomed while the window was open — strict round-trip.
- If a second badge is clicked while the window is already open, the captured pan/zoom from the *first* open is preserved through the transition: restore from, animate to, rebind capture at this first open's snapshot only if no existing capture is held.
- Configurable via `info_window.pan_zoom: {enabled: bool, zoom: number|"fit"}` on the badge set, defaulting to enabled with `"fit"` behavior.

#### Development (planned)

- Capturing once-per-open (not rebinding on every click) is important so that rapid clicks on adjacent hosts don't erase the original viewport state.
- Fit-with-margin matches the projection's existing fit behavior; a fixed zoom number is the escape hatch for cases where the default doesn't land well.

## Out of scope

- Write actions from the info window (resolving findings, creating exceptions, etc.). The window is read-only in v0.
- Full-text search or filter inside the window. The section row list is whatever the search returns, in that order.
- Persisted user preferences for window position or size.
- Accessibility beyond ESC + focus management basics (full screen-reader auditing is a separate effort).
