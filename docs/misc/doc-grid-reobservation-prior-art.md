---
title: Re-observation is not change — prior art for periodically re-collected inventories
date: 2026-09-02
status: research
audience:
  - developer
  - llm
related:
  - tap#322
  - tap_grid/specs/spec-grid-flip.md
  - tap_grid/specs/spec-grid-history.md
  - github-core#14
---

> **Prior-art survey, 2026-09-02**, run from the viz-git-serious session after the first scheduled
> github_core collector pass showed every unchanged node gaining a history version per pass
> (tap#322). Written by an AI research agent from public sources, each pinned by URL; local anchors
> verified on `session/viz-git-serious`. Nothing here is canon — the requirement changes live in
> the grid specs.

# The problem in one sentence

A collector re-emits the whole configuration layer every pass; the importer upserts by deterministic
id (no duplicates: 0 duplicate natural keys and 0 duplicate edges after 80 batches), but it rewrites
the typed row's `batch_id` and `flip_map` on every pass, so an unchanged node gains a history version
each time — ~1,600 nodes × 144 passes/day at a ten-minute schedule.

# TAP's own position

- `spec-grid-flip.md:57` — a FLIP value is "the batch that last **set** the current canonical
  value". A re-observation that writes an identical value did not set it.
- `spec-grid-history.md:28` — "A history record exists because TAP stored a change, not because an
  external source observed something."
- `tap_grid/grift/importer.py` ~2827 — the no-op short-circuit exists for the **spine** (name,
  dimensions compared to the persisted row; a no-op does not bump version or `updated_at`) and
  stops short of the typed row.

The specs already say re-observation is not history. The importer disagrees with them.

# Survey

| System | "Seen again, unchanged" | Change detection | Absence | Past-run membership | Rows/node/run |
| --- | --- | --- | --- | --- | --- |
| cartography | `lastupdated` overwritten in place to the run's update tag; `firstseen` once | none (MERGE) | cleanup job deletes `lastupdated <> tag`; MERGE first, delete after | latest run only | 0 |
| CloudQuery | row overwritten by PK; `_cq_sync_time` bumped | none | `overwrite-delete-stale` at sync end | latest only (append mode keeps all, no dedupe) | 0 / 1 |
| ServiceNow CMDB / IRE | `last_discovered` updated "even when no other CI attributes are updated"; `sys_updated_on` untouched | field-level reconciliation by source precedence | staleness on `last_discovered` age → retirement task | latest only | 0 |
| Wiz / Guardrails / Steampipe | full sync; assets age out on `LAST_SEEN` / change-event log / no persistence | events | last-seen age | latest only | 0 |
| Kubernetes | nothing server-side; `resourceVersion` changes only on writes; informer resync re-delivers, client compares | version counter | explicit DELETED event | no (stream) | 0 |
| Terraform | state serial increments only when the state differs; 1.3.0 regressed to rewriting state per no-op and shipped a fix | structural equality | refresh drops objects not found (doc warns bad creds look like deletion) | no | 0 |
| osquery | differential logs only when the cached result changes; run visible via `counter` | set diff → added/removed | `removed` line | snapshot mode yes; differential no | 0 / N |
| SCD Type 2 | hash compare; equal → no new row | row hash | expiry on current row | no | 0 |
| Datomic | redundant datoms not added; the transaction itself is never redundant | value equality | retraction | tx exists; touched-set not recorded | 0 datoms, 1 tx |
| git | identical content → same object | content address | path absent from tree | every commit's tree is a full snapshot | 0 blobs |
| Security Monkey | config dict compared (ephemeral paths excluded); unchanged → no write | durable hash | inactive-revision tombstone | no | 0 |
| Debezium / CDC | none, log-driven | source WAL | delete event + tombstone | no | 0 |
| W3C PROV | `used(activity, entity)` — touched without producing | `wasGeneratedBy` / `wasRevisionOf` | `wasInvalidatedBy` | yes, by design | 1 relation |

**Nobody keeps a versioned row per re-observation.** Terraform did it by accident once and fixed it.

# Three representations recur

| | Who | Trade-off |
| --- | --- | --- |
| **A. In-place last-seen stamp** | cartography, CloudQuery, ServiceNow, Wiz | zero growth; reconciliation is one comparison; a past run is not reconstructible; poisoned if a non-enumerating writer touches the stamp (ServiceNow needed a flag to stop integrations resetting it) |
| **B. Diff-before-write, change-only log** | SCD2, Security Monkey, osquery, Datomic, Kubernetes, Terraform, Debezium | exactly the history semantics wanted; alone it records nothing about the pass, so "not observed" and "observed unchanged" collapse unless the run is recorded separately |
| **C. Full membership snapshot per run** | git, osquery snapshot, PROV `used` | every run reconstructible; growth is linear and must be bounded |

# Recommendation for TAP (tap#322)

1. **Importer rule = B.** Compare incoming domain fields to the persisted typed row, excluding the
   ephemeral set (`batch_id`, `flip_map`, timestamps). Equal → skip the typed-row save entirely: no
   version bump, no history row, no `flip_map` rewrite. `flip_map` then means "batch that last
   changed the field", which is what `spec-grid-flip.md` already says with the word "set"; tighten
   the wording. A stored content hash is an optional accelerator, never the mechanism.
2. **Membership = A plus a windowed C.** A non-versioned `last_observed_batch_id` / `last_observed_at`
   on the spine, written with `.filter().update()` exactly as the spine no-op path does, is what
   reconciliation reads. Beside it, a narrow observation record so "which entities did batch X
   observe" stays answerable for no-op passes — either a table `(batch_id, entity_id, outcome ∈
   created|changed|unchanged|tombstoned)` with a retention window, or a per-batch `observed_entity_ids`
   set on the batch record (one row per batch, ~26 KB for 1,612 ids, 1,612× fewer rows, weaker
   Gryphon joinability). Both reconstruct a batch; the table joins, the set is cheap.
3. **Reconciliation (github-core#14) reads the summary, gated on scope completion.** Absence =
   `last_observed_batch_id != current full-enumeration batch` for entities in the collector's scope,
   evaluated only after the pass finished enumerating that scope (a credential failure must not read
   as mass deletion). Incremental passes never stamp config-layer nodes. Deletion is a tombstone
   version, not a row delete — absence is a change and belongs in history.

# Failure modes by option

| Option | Failure | Mitigation |
| --- | --- | --- |
| Diff-before-write only | a pass with zero writes is invisible | record the batch + the summary stamp |
| `last_observed_*` only | cannot reconstruct batch X; a partial pass stamps some entities and reconciliation deletes the rest | gate on completion; windowed membership |
| Membership table | linear growth (today's churn volume at a tenth the width) | retention window; or the per-batch id-set variant; the summary column survives pruning |
| Content-hash only | no membership, no absence; a second copy of a fact | cache only; compare values |
| A non-collector writer touches last-observed | staleness silently suppressed | only full-scope collector passes stamp; record scope on the batch |

The done-test in tap#322 maps onto this directly: two idle passes → version unchanged, `last_observed_at`
moves, two `unchanged` observations; one upstream change → exactly one `changed` observation and one version.

# Sources

cartography module and analysis-job docs · CloudQuery destination spec, PostgreSQL plugin docs, issue 17913 ·
ServiceNow community threads on `last_discovered` / IRE and KB0820474 (title only, login-walled) · Brinqa Wiz
connector doc · Turbot Guardrails reports · Steampipe caching guide · Kubernetes ObjectMeta and API-concepts
pages, client-go cache package · Terraform refresh docs, issues 27827 and 32060, PR 32123 · osquery logging
docs · Kimball Type 2 · Datomic transaction-data reference · XTDB bitemporality docs (no statement on
identical-put dedupe: NOT OBSERVABLE) · Pro Git internals · Netflix Security Monkey `watcher.py` · Red Hat
Debezium change-events guide · W3C PROV-DM and PROV-O. All fetched 2026-09-02.
