# Batch Viewer Page — v0

## Philosophy

A **batch** is TAP's unit of provenance: every node/edge mutation is stamped with the `batch_id` that wrote it (FLIP), and GRIFT imports are batch-scoped. There are many batches on any grid (collector runs, grift imports, service mutations), but no way to *see* what one did. This page makes a single batch legible — what it **added** (nodes + edges), what it **removed** (deletes + purges), and the batch's own metadata — for any batch from any plugin.

It is a generic platform view (the panels live in `tap_web`), reached from the **Administrivia** backend section (the pages are seeded by the `administrivia` plugin, which owns that `/administrivia/*` namespace). Two surfaces work together: a **roster** at `/administrivia/batches` (the discoverable nav entry — every batch, newest-first) and the **single-batch viewer** at `/administrivia/batch` (hidden from nav; reached by clicking a roster row or by deep link).

## The representation problem (and how each section is sourced)

`batch_id` lives on the typed `BaseModel` rows (and on `Edge`, which is a `BaseModel`), **not** on the `Entity` spine — so "everything in batch X" is a cross-type question best answered by Gryphon, not an ORM filter. Each section has a different, deliberately-chosen source:

| Section | Source | Recoverable? |
| --- | --- | --- |
| **Nodes added** | Gryphon `MATCH (n) WHERE n.data.batch_id = $bid AND n.data.deleted_at IS NULL` | ✅ live on the grid |
| **Edges added** | `Edge.objects.filter(batch_id=bid)` — `from_entity` / `edge_type` / `to_entity` | ✅ live on the grid |
| **Deletes (tombstones)** | nodes with `batch_id = bid AND deleted_at IS NOT NULL` (soft-deleted rows persist) | ✅ tombstones remain in the DB |
| **Purges (hard deletes)** | a persisted **removal manifest** on the batch (`metadata.removals`) — *the rows themselves are gone* | ⚠️ only if the batch recorded a manifest |

The purge row is the crux the design has to solve honestly: a **purge is a hard delete**, so the entity is no longer on the grid and `batch_id` can't find it. The only way to show *what* a batch purged is for the batch to have **recorded the manifest before deleting** (entity_id, entity_type, name, action). v0 reads `batch.metadata["removals"]`; the importer change that writes it is `req-web-batch-viewer-removal-manifest` below. Until a batch carries a manifest, the purges section says so explicitly rather than rendering a silently-empty (and misleading) table — the `unknown ≠ empty` discipline.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-batch-viewer-roster | [Batch Roster Page](#batch-roster-page) | Implemented | `tap_web` `batch-list` panel; `administrivia` page at `/administrivia/batches`; the discoverable nav entry; rows click through to the single-batch viewer |
| req-web-batch-viewer-panel | [Batch Viewer Panel + Page](#batch-viewer-panel--page) | Implemented | `tap_web` `batch-viewer` panel; `administrivia` page at `/administrivia/batch` (hidden from nav); latest-by-default + deep-link |
| req-web-batch-viewer-header | [Batch Header](#batch-header) | Implemented | name, source, status, started/closed, description, at-a-glance counts |
| req-web-batch-viewer-nodes | [Nodes Added Table](#nodes-added-table) | Implemented | Gryphon by `data.batch_id`; Tabulator (type, name, entity_id), grouped by type |
| req-web-batch-viewer-edges | [Edges Table](#edges-table) | Implemented | `from → type → to` with names; each endpoint flagged in-batch vs external |
| req-web-batch-viewer-deletes | [Deletes Table](#deletes-table) | Implemented | tombstones (`batch_id` + `deleted_at`) |
| req-web-batch-viewer-purges | [Purges Representation](#purges-representation) | Implemented | reads `metadata.removals` (action=purge); honest empty/absent state |
| req-web-batch-viewer-removal-manifest | [Removal Manifest Persistence](#removal-manifest-persistence) | Proposed | importer records `metadata.removals` so purges become recoverable |

### Batch Roster Page
----
RID: `req-web-batch-viewer-roster`

Status: `Implemented`

A `tap_web` panel type `batch-list` (`tap_web/panels/batch_list/`), seeded by the `administrivia` plugin at **`/administrivia/batches`** — the discoverable Administrivia nav entry. It lists **every** batch on the grid, newest-first, with columns: name, source, status, started_at, closed_at, plus an at-a-glance count band (total / closed / open / failed). Each row clicks through to the single-batch viewer at `/administrivia/batch?batch_entity_id=<id>`.

**Why a dedicated panel rather than the generic search-driven `table` panel:** a batch's most useful columns — `status`, `started_at`, `closed_at` — are lifecycle fields the `Batch` model deliberately keeps **out** of its writeable `FIELD_CRUD_SCHEMA`, so they never enter the Gryphon node `data` envelope that the generic table reads (they render blank). `batch-list` reads the `Batch` ORM rows directly, so those fields are available. It emits a `raw`-mode Tabulator (`panel-table.js`); each row carries a `_url` string, and raw-mode rows with a `_url` become click-through navigations (the generic raw-table row-nav hook added alongside this panel).

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-web-batch-viewer-roster-1 | Registered + Routed | Implemented | `batch-list` is registered; `/administrivia/batches` resolves and mounts it as the discoverable nav entry. |
| req-web-batch-viewer-roster-2 | Lifecycle Columns | Implemented | status / started_at / closed_at render (read from `Batch` ORM, not the data envelope). |
| req-web-batch-viewer-roster-3 | Row Click-Through | Implemented | A roster row navigates to `/administrivia/batch?batch_entity_id=<id>` via the raw-mode `_url` hook. |

### Batch Viewer Panel + Page
----
RID: `req-web-batch-viewer-panel`

Status: `Implemented`

A `tap_web` panel type `batch-viewer` (`tap_web/panels/batch_viewer/`). The page is seeded by the `administrivia` plugin at **`/administrivia/batch`** (bare-slug, **hidden from nav** — `discoverable: false`; reached via a roster row click or deep link). The panel resolves a batch via `tap_web.panels.entity_resolution`: deep-link `?batch_entity_id=<id>` wins; otherwise the fallback selects the **most recent batch** (`MATCH (b:batch) WHERE b.data.started_at IS NOT NULL ORDER BY b.data.started_at DESC LIMIT 1`). A sequence-nav selector walks batches newest-first.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-web-batch-viewer-panel-1 | Registered + Routed | Implemented | `batch-viewer` is registered; `/administrivia/batch` resolves and mounts it. |
| req-web-batch-viewer-panel-2 | Latest Default + Deep Link | Implemented | Bare URL shows the latest batch; `?batch_entity_id=<id>` pins one. |

### Batch Header
----
RID: `req-web-batch-viewer-header`

Status: `Implemented`

A band + metadata footer from the resolved `batch`: `name`, `source`, `status` (pill), `started_at` / `closed_at`, `description`, and an at-a-glance stat row (nodes added, edges added, deletes, purges).

### Nodes Added Table
----
RID: `req-web-batch-viewer-nodes`

Status: `Implemented`

All live nodes stamped with the batch, via Gryphon `MATCH (n) WHERE n.data.batch_id = $bid AND n.data.deleted_at IS NULL`. Rendered as a Tabulator (sortable + quick-filter), columns: entity_type, name, entity_id; grouped by entity_type. **Semantics note:** `batch_id` is FLIP's *last-writer* stamp, so this is "nodes the batch currently owns" — a node later re-written by another batch moves to that batch. For a freshly-imported batch this equals "nodes added," which is the common case; the header labels it accordingly.

### Edges Table
----
RID: `req-web-batch-viewer-edges`

Status: `Implemented`

`Edge.objects.filter(batch_id=bid)`, rendered as `from-name → edge_type → to-name` (the tractable shape — never raw entity_ids). Each endpoint is flagged **in-batch** (its node is in this batch's node set) or **external** (a pre-existing node the batch linked to), so cross-batch wiring reads at a glance. Tabulator, sortable + quick-filter, groupable by edge_type.

### Deletes Table
----
RID: `req-web-batch-viewer-deletes`

Status: `Implemented`

Tombstoned nodes the batch removed: `batch_id = bid AND deleted_at IS NOT NULL`. Soft-deleted rows persist in the DB, so these are fully recoverable. Columns: entity_type, name, entity_id, deleted_at.

### Purges Representation
----
RID: `req-web-batch-viewer-purges`

Status: `Implemented`

Reads `batch.metadata["removals"]` filtered to `action == "purge"` — `{entity_id, entity_type, name}` recorded *before* the hard delete. When the manifest is present, renders a table; when **absent** (batches imported before the manifest exists, or batches with no removals), renders an explicit informational state distinguishing the two: *"no removals recorded"* vs *"this batch predates the removal manifest — purged rows are hard-deleted and not retained."* Never a silently-empty table that reads as "nothing was purged."

### Removal Manifest Persistence
----
RID: `req-web-batch-viewer-removal-manifest`

Status: `Proposed`

For purges to be representable at all, the batch must record what it removed *before* removing it. The GRIFT importer (and the service-layer removal path) should write a `metadata.removals` array onto the batch — `[{entity_id, entity_type, name, action: "tombstone"|"purge"}]` — at close. `batch.metadata` is already a `JSONField`, so no migration is needed; this is a localized importer change. Deletes (tombstones) corroborate against the live DB; purges depend on it entirely. Until then, the purges section degrades honestly (above). *(Alternative considered: recover purges from `simple_history` `history_type="-"` rows — possible but requires iterating every typed historical table and assumes the purge path triggers history; the manifest is the cleaner, single-source contract.)*

## Out of Scope (v0)

- **Per-field FLIP diffs** (which batch set which field on a multi-batch node) — the flip_map exists; a field-provenance view is future.
- **Cross-batch lineage** (a node's full batch history) — this page is one batch's footprint, not an entity's timeline.
- **Mutating actions** (re-run, roll back a batch) — read-only viewer.
