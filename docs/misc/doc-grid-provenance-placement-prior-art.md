---
title: Where write provenance lives — header or payload? Prior art for moving the batch pointer to the Entity spine
date: 2026-09-02
status: research
audience:
  - developer
  - llm
related:
  - tap#323
  - tap#322
  - tap_grid/specs/spec-grid-node.md
  - tap_grid/specs/spec-grid-flip.md
  - docs/misc/doc-grid-reobservation-prior-art.md
---

> **Prior-art survey, 2026-09-02**, commissioned to support (or refute) tap#323: moving the row-level
> "last changed by batch" pointer, and a new "last observed by batch / at" stamp, from the typed
> BaseModel row to the Entity spine, with the per-field FLIP map staying on the typed row. Written by
> an AI research agent from public sources pinned by URL; local anchors verified on
> `session/viz-git-serious`. Sources that could not be fetched are marked as snippet-sourced.

# The question

In established systems, where does write provenance live — on the common object header every object
shares, or on the type-specific payload — at what granularity, and how is "what did transaction X
change" answered across all types in one query?

# Survey

| System | "Last changed by" lives on | Per-field provenance | Granularity | "What did X change?" | Per-write cost |
| --- | --- | --- | --- | --- | --- |
| OpenStreetMap | **common header**: `version`, `changeset`, `timestamp`, `uid` on every node/way/relation | none (tags are payload) | object + changeset | changeset is first-class; `/changeset/#id/download` returns osmChange | zero (same row) |
| Wikibase / Wikidata | **common header**: MediaWiki page → revision (`rev_actor`, `rev_timestamp`, parent) | none per statement | entity + revision | revision table by page or by actor/time | one revision row per edit |
| Kubernetes | **common header** `ObjectMeta`: `resourceVersion`, `generation` | **on the header**: `managedFields[]` (manager, operation, time, field tree) | object + field | not answerable by object; watch/CDC by resourceVersion; audit log separate | header grows O(fields × managers) |
| PostgreSQL | **hidden header on every row**: `xmin`, `xmax`, `cmin`, `cmax` | none | row version + transaction | `WHERE xmin = X` per table (no cross-table index); commit timestamps optional and vacuumed | free (tuple header) |
| Datomic | every datom carries `tx`; the transaction is an entity | inherent (datom = E,A,V,Tx,Op) | field + transaction | log indexed by tx: `tx-range` returns all datoms of the tx across all entities | one datom per changed attribute |
| Delta Lake CDF | **metadata columns** `_change_type`, `_commit_version`, `_commit_timestamp` | none | row + commit | `table_changes(start, end)` | change files only for update/delete |
| Iceberg v3 | **reserved metadata columns** `_row_id`, `_last_updated_sequence_number` on every row; file → snapshot in the manifest | none | row + snapshot | snapshot → manifests → files | inherited until rewrite |
| Salesforce | **system fields on every object**: Created/LastModified by/date, `SystemModstamp` (indexed) | separate per-type `<Object>History` ledger, opt-in, capped | object + field | delta by `SystemModstamp >`; per-type history = per-type union | same-row stamp + history rows |
| ServiceNow | **global fields on every table**: `sys_updated_by/on`, `sys_mod_count`, `sys_created_*` | one shared ledger `sys_audit`, one row per changed field | object + field | `sys_audit` by user/time across ALL tables in one query | same-row stamp + N audit rows |
| W3C PROV | relation from the entity: `wasGeneratedBy(e, a, t)`, `wasAttributedTo` | qualified relations | entity + activity | inverse traversal from the activity | edges per generation |
| Dolt | no per-row column; commit graph; `dolt_history_<t>` synthesises commit onto rows | `dolt_diff_<t>` | row + commit | two-level: DB-wide `dolt_diff` lists tables, then per-table diff | structural diff |
| TerminusDB | commit graph of triple deltas (docs unreachable; snippet-sourced) | triple-level | triple + commit | layer difference | layer append |
| Neo4j | nothing built in; APOC trigger `created`/`updated` properties; CDC ledger opt-in (`txId`) | none | node + tx (CDC) | CDC by `txId` | trigger / CDC log |
| JanusGraph | nothing built in; meta-properties offered | per property, app-authored | property | app-defined | app-defined |
| git | **commit only**; blobs carry nothing | none | transaction | `git log -- path` walks trees | zero on content |

# Convergence

**Row-level "last changed by": the common header wins, nearly unanimously.** OSM, Wikibase, Kubernetes,
Postgres, Salesforce, ServiceNow, Iceberg and Delta all put the transaction pointer and timestamp on
the layer every object shares. The reasons repeat: it is free because the row is being written anyway;
generic infrastructure (replication, delta sync, optimistic locking, recent-changes views, tombstones)
must read it without knowing the type; and one indexed column across all types answers "touched by X
since T" in one scan. The only systems that keep it off the object are those where the object *is* the
transaction (git) or the field is the atom (Datomic, TerminusDB).

**Per-field provenance splits three ways, and the header option is the one people complain about.**
Kubernetes put it on the header and got "over half of a 640-line object" (kubernetes#90066), a
hide-by-default fix in kubectl 1.21, and an open item to compress field names. Salesforce and
ServiceNow keep per-field in a ledger. Datomic makes the field the unit. TAP's `flip_map` on the typed
row is the Kubernetes shape minus the shared-header cost.

**"What did X change" is never answered from the object header alone.** Every system that answers it
well has a transaction-indexed structure: osmChange, the Datomic log, a Delta commit range, Iceberg
snapshots, Dolt's commit-to-tables diff, Neo4j CDC, git's commit tree. The header pointer says who
touched the object *last*.

# The argument for tap#323

**For.** It is the established placement for the row-level pointer. It turns "what did batch X change"
from N indexed scans over N typed tables (plus edges) into one indexed scan over the spine — Dolt's
two-level pattern: the spine answers *which entities and types*, the typed row answers *which fields*
via `flip_map`. It serves Player 3: a machine enumerates a batch's footprint without the type registry.
It matches `Entity.version`, which already lives on the spine and increments on every canonical
mutation.

**The caveat the evidence forces.** The spine pointer is last-writer-wins: it answers "what did batch X
change" only for entities X touched *last*. OSM lives with exactly this — an element shows only its
latest changeset; the full answer needs the changeset ledger. TAP's ledger for that question is the
typed history rows (stamped per version) plus tap#322's unchanged set on the batch; the pointer is not
the ledger and should not be sold as one.

**Verdict.** Move the row-level pointer and the observed stamp to the spine; keep `flip_map` on the
typed row; the batch's complete footprint stays a ledger question answered by history + the unchanged
set.

# Traps that map onto TAP

1. **Observed stamps must not dirty the row.** ServiceNow sets `last_discovered` on every identification
   and deliberately does not bump `sys_updated_on`; Kubernetes found heartbeating through the object's
   status too expensive and moved node heartbeats to a separate `Lease` object. TAP's `Entity.updated_at`
   is `auto_now` and `version` increments on every canonical mutation. The stamp must go through a
   queryset `.update()` (which bypasses `auto_now` and the version bump — the spine no-op path already
   does this) and must never route through `save()`.
2. **Two timestamps with subtly different meaning.** Salesforce's `SystemModstamp ≥ LastModifiedDate`,
   only one indexed, integrations pick the wrong one. Name TAP's pair so the semantics are in the name
   (`last_changed_batch_id` / `last_observed_batch_id`), state the invariant `last_observed_at ≥
   last_changed_at`, index the one delta-sync reads.
3. **Header bloat.** Every spine query pays for spine width; keep per-field maps off it.
4. **Bypass paths skip the stamp.** ServiceNow's `autoSysFields(false)`; TAP's FLIP "silently skipped
   without an active batch" (`spec-grid-flip.md:117`). Once the spine pointer is the cross-type
   provenance surface, a null pointer on a service-layer write should be a guard failure, not silence.
5. **Non-atomic changesets.** OSM elements are visible before the changeset closes and an element
   modified twice in one changeset shows only its final state. TAP batches behave the same; document it.
6. **Raw transaction ids rot.** Postgres `xmin` wraps; commit timestamps are optional. TAP's UUIDv7
   batch ids do not wrap, but "when" should stay on the row (`_at`) rather than be derived only by
   joining a batch row that may be pruned.

# Systems keeping both "last changed" and "last observed" on the header

- **ServiceNow CMDB**: `sys_updated_on` (changed) + `last_discovered` (observed) + `first_discovered` —
  the closest analog to a collector-fed graph.
- **Kubernetes NodeCondition**: `lastTransitionTime` (changed) + `lastHeartbeatTime` (observed).
- **Salesforce**: `LastModifiedDate` (user change) + `SystemModstamp` (any system touch) — changed vs
  touched, the same shape.
- Wiz `LAST_SEEN`, Chronicle `first_seen_time` / `last_discover_time`: snippet-sourced, unverified.

# Sources

OSM wiki (Elements, API v0.6, Changeset, OsmChange) · MediaWiki Revision table, Wikibase DataModel and RDF
dump format · Kubernetes server-side apply, apimachinery `types.go`, issues 90066 and 73723, node-status ·
PostgreSQL system columns, info functions, routine vacuuming · Datomic data model and Log API · Delta Lake
CDF · Apache Iceberg `format/spec.md` · Salesforce KB 000387261 (developer object reference 403'd) ·
ServiceNow KB0547662 and community threads (docs portal not fetchable) · W3C PROV-DM · Dolt system tables ·
TerminusDB (522'd; snippets) · Neo4j CDC output schema, APOC trigger thread · JanusGraph advanced schema ·
Pro Git internals, git-log. All fetched 2026-09-02.
