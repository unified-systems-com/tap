# Batch Playground Specification

## Philosophy

The GRIFT import path is where every collector's observations become rows: identity by id, batch-local refs through the gate, removal sections, optimistic concurrency, dangling edges, multi-batch atomicity. Its unit tests prove the paths their authors thought of; the intra-batch duplicate gap (Issue# 602 - tap) was found by a *question*, because no test asked it. A **corpus** is the other half: a committed set of small, eyeballable import scenarios, each a starting grid, one or more documents imported in order, and the exact outcome they must produce, run in the lanes forever, so the importer is confirmed to do exactly what it did — no more, no less — every time anything near it changes. The shape is the cascade confirmation corpus's (`spec-grid-cascade-corpus.md`, Issue# 578 - tap) and, behind it, Gridkin's: scenarios are data; the expected answer is authored by a human; an independent model must agree with every hand answer at load time; a known defect is tracked as a scenario that must fail in its exact shape, never papered over. Ruled by George 2026-09-18: it lives in `tap_grid` for now, to be spun out with the cascade corpus later.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Exact | Every scenario names exactly which rows exist afterwards (by name, with liveness and version), which batches committed, skipped or failed, and the exact issue codes and paths of a refusal; the runner proves nothing else was written or changed |
| 2. | Eyeballable | A scenario is one JSON object a reader can check against the import spec without reading Python |
| 3. | Oracle-bearing | Expected outcomes are hand-authored and cross-checked by a reference model that restates the import rules from the specs — pure Python, no ORM — and whose declaration table is proven against the registry |
| 4. | Honest about defects | A scenario pending a named issue is an expected failure only when the checker's assertions mismatch; a fixture error or a worker error is a hard failure whatever the tag says |
| 5. | Timed as well as shaped | Two-writer interleavings run as real cases on the real database, on the cascade corpus's timing harness, as named schedules that state their acceptable serial outcomes |
| 6. | Three truths | Persisted state, the API report and provenance are each compared, and a scenario passes only when all three agree; generated ids are symbolic |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-batch-corpus-format | [Scenario Format](#scenario-format) | Implemented | The JSON shape of a `.batch.json` family file |
| req-grid-batch-corpus-runner | [Runner Contract](#runner-contract) | Implemented | Build through the service layer, import through `grift_import`, assert exact rows, no collateral, the records and the result shape |
| req-grid-batch-corpus-oracle | [Oracle Agreement](#oracle-agreement) | Implemented | A reference model agrees with every hand answer at load; its declaration table agrees with the registry |
| req-grid-batch-corpus-timing | [Timing Family](#timing-family) | Implemented | Two-writer interleavings made deterministic with the identity lock and row locks |
| req-grid-batch-corpus-nongoals | [Non-Goals](#non-goals) | Implemented | What the corpus deliberately does not do |
| req-grid-batch-corpus-datasets | [Authored Datasets](#authored-datasets) | Implemented | Five small datasets adapted from named prior art, each a family of its own |

### Scenario Format
----
RID: `req-grid-batch-corpus-format`

Status: `Implemented`

#### Implementation

A family file lives at `tap_grid/batch_corpus/scenarios/<family>.batch.json` (role `batch`, `spec-tap-json-files.md`) and is validated at load against `tap_grid/batch_corpus/batch.schema.json` (every field described). One family per file. The first pass: `identity`, `refs`, `removals`, `occ`, `dangling`, `multibatch`, `spine`, `retired`. The second pass (Issue# 613 - tap): `reload` (a deleted node or edge re-sent by id and by ref, George's first family), `collision` (identity overlap revealed after ref resolution, Issue# 606 - tap), `rewriting` (self-loops, cycles, diamonds, mixed endpoints, look-alike payload text), `provenance` (both spine projections, explicit empty dimensions — Issue# 608 - tap, false/zero/empty values, replace resets, batch attribution), `atomic` (failure at first/middle/last op, counts of a rolled-back batch — Issue# 607 - tap), `replay` (fresh-batch re-observation while Issue# 322 - tap is open, retry after a rollback, label reuse), `hotlink` (deferred consistency, the Issue# 351 - tap move), and the five authored datasets (`req-grid-batch-corpus-datasets`). A scenario has:

- `grid` — the starting grid: nodes by name, type and payload; edges by name from node to node; names `tombstoned` before the first import, then names `cascaded` (deleted with `cascade="contained"` along `PG_NESTS__grid_fixtures`, which the test declares as the fixture node's containment edge before the build). Types are the reference model's declaration table: `panel` and `page` (declared key on `slug`, not unique; a page carries the `page-panels` exact hotlink), the `grid_fixtures__*` playground types (undeclared), `landing_page` (retired).
- `imports` — the `grift_import` calls in order, each one document of batches. A node is addressed by `id` (the name's id: minted at first sight, or a grid row's) or by `ref` (a batch-local ref the gate resolves); an edge endpoint is a name (`from`/`to`, sent as `from_ref` when it names a ref node of the batch, else as the name's id) or an explicit `from_ref`/`to_ref`; `deletes` and `purges` sections carry targets by name; `dangling_edge_mode` and `seed_boundary` (the retired-type strip) are per import; `settings.debug` is per scenario. **Names are scenario-global**: an `id` name re-sent is the same id, a `ref` name re-sent is the same source object, a ref that finds another row is an alias of it, and a name declared nowhere must be a listed `phantom`.
- `expected` — per import: `success`, each batch's state (`committed` / `skipped` / `failed` / `refused`), the exact `errors` as (code, path) pairs, optionally the exact warning codes and `counts` spot checks (what a batch **committed**, never a rolled-back prefix); then **`live` and `tombstoned` as exact name → version maps and `absent` as the exact list of names with no row**, `resolves` (refs that found a row), optional `dimensions` (exact `Entity.dimensions` for rows whose envelope declared them), `fields` (typed-row values read back through `get_node`), `events` spot checks and a `note`. Node envelopes may declare `dimensions`; an explicit `{}` on a replace is a value (Issue# 608 - tap).
- `covers` — the requirement and acceptance-criterion ids the scenario exercises; every one must resolve to a row in `spec-grid-import-grift.md`, `spec-grift-v0.md`, `spec-grid-entity.md`, `spec-grid-service-delete.md` or `spec-web-page.md`.
- `pending` — an `owner/repo#n` the scenario waits on, verified in-body (below).

#### Development

**Second pass (Issue# 613 - tap, from Codex's corpus review and George's two families of 2026-09-18).** Read first, in the order the issue ranked them, and borrowed as shapes with TAP's answers authored independently: **FHIR R4 (v4.0.1) transaction rules** (`hl7.org/fhir/R4/http.html` §3.1.0.11.2: all-or-nothing; temporary `urn:uuid` ids rewritten wherever they appear; conditional identity; *"if any resource identities (including resolved identities) overlap … the transaction SHALL fail"*) and its **example transaction bundle** (`bundle-transaction.json.html`, CC0) gave the `rewriting` family, the `encounters` dataset and the collision family's framing. **DataScript `test/datascript/test/upsert.cljc`** (master, read 2026-09-19: upsert by one and two identifying attributes, tempids and string tempids, lookup refs, *"Conflicting upsert: … resolves to 1, but entity already has :db/id 2"*, *"Conflicting upserts: [:name] resolves to 1, but [:email] resolves to 2"*, upsert over an intermediate db, two tempids resolving to one entity) gave the three-aliases case and the ref-plus-explicit-id cases — DataScript merges where TAP refuses, so its inputs were borrowed and its outcomes were not. **PostgreSQL `src/test/regress/sql/insert_conflict.sql`** (master: composite-key inference, a statement conflicting with itself, DO NOTHING versus DO UPDATE) framed the `inventory` dataset's key discipline, and **`src/test/isolation/specs/insert-conflict-specconflict.spec`** (a controller session holds advisory locks and releases them in a named order so every permutation is deterministic; "s1 inserts, s2 updates" and its mirror) is the model for the timing schedules: a holder takes the lock, the contender is observed blocked on it by pid, the holder's work commits, the contender proceeds — permutations, never sleeps. **JSON:API Atomic Operations** (`jsonapi.org/ext/atomic`: `lid` scoped to the request; *"a failure to perform any operation MUST invalidate any effects of preceding operations"*; `atomic:results` in one-to-one correspondence; error `source.pointer` to the failing operation) gave the `atomic` family's failure-position cases and the result-correspondence checks; its strict-sequencing rule was not imported. **Salesforce Composite** (dependency chains; a failed prerequisite fails its dependents; outer success is not subrequest success) gave the `chain` dataset and the rule that every reporting layer is read. **ServiceNow IRE** (identification by declared rules; duplicate-in-payload versus duplicate-existing) gave the `inventory` dataset's error shapes. **SQLite's upsert old/new-values bug** gave the discipline that a final payload alone proves nothing about intermediate records: typed rows and events are read back, not inferred. **STIX 2.1** indicator/sighting shapes gave the `sightings` dataset. Composite keys are represented as `(type, slug)` only: no core or fixture type declares a composite `NATURAL_KEY`, and adding one to the `grid_fixtures` plugin is a release of another repository (named under Non-Goals). Two hand answers were corrected by the model at load — a replayed batch beside a fresh batch on one id is a refused file (file-wide id uniqueness precedes the skip), and a cascade's events precede the run — and one model fault was corrected by a hand answer (the intra-batch duplicate key is `(type, values)`, never values alone).

Prior art searched first (Issue# 603 - tap), in the Gridkin tradition of borrowing intent and never porting. **PostgreSQL's `insert_conflict.sql` regression** gave the identity family its spine — DO NOTHING versus DO UPDATE against an existing row, and *self-conflicting rows in one statement* (the origin of the intra-batch duplicate scenarios); **SQLite's `upsert1.test`** added "multiple rows conflicting in one statement" and the discipline of an error case per invalid conflict target. **JSON:API's Atomic Operations extension** (`lid`, local identity scoped to one request; "a failure to perform any operation MUST invalidate any effects of preceding operations") and **Salesforce Composite Graph** (`referenceId` scoped to a graph, all-or-nothing per graph, other graphs still commit) together gave the refs family's batch-locality and the multibatch family's per-batch atomicity with partial landing. **ServiceNow's Identification and Reconciliation Engine** (items matched by identification rules, `INSERT`/`UPDATE` per item, duplicates prevented by the rule rather than the payload) framed the gate's "the search is declared, never supplied" cases. **openCypher TCK `Merge1`–`Merge9`** (merge node when none exist, when it exists, when finding multiple elements, ON CREATE/ON MATCH, merging relationships using merged nodes) gave the mint/find/ambiguous trio and the edge-between-refs case. **Django's fixture tests** (`test_forward_reference_fk_natural_key`, `test_unmatched_identifier_loading`) gave the forward-reference and unresolvable-identifier cases; **CouchDB's conflict model** (a stale `_rev` is a 409; `_bulk_docs` with `new_edits=false`) gave the OCC family's expected-version-on-a-moved-row shape; **Kafka Connect's JDBC sink `BufferedRecordsTest`** (insert-then-delete-then-insert in one buffer forces a flush; tombstone records delete by key) gave "deletes run after the upserts" and the delete-target policy cases; **OpenCTI's STIX ingestion** (deterministic ids from contributing properties, which TAP rejected for the id and kept for the search) gave the two-panels-one-slug-by-id contrast. The in-house corpora gave the rest: the cascade corpus's delta-based records, verified pending and corrupted-run negatives; Gridkin's oracle-at-load. Two importer questions were found by *running* the scenarios, not reading the code, and are filed with their reproducers: an edge onto a tombstoned endpoint was created (Issue# 609 - tap — ruled 2026-09-18: no live edge may point at a tombstone, `req-grid-service-delete-tombstone-7`; the scenario now expects the refusal), and a permissive-mode skipped edge counts as a batch error (Issue# 610 - tap); the timing family found a third (Issue# 611 - tap, below — fixed with 609: every mutating verb locks its target row first).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-batch-corpus-format-1 | Schema-validated at load | Implemented | A family file that does not fit the schema, a name that does not resolve, an endpoint or target declared nowhere, or a type outside the model's table is refused before any database work, naming the file and scenario. | `tap_grid/batch_corpus/loader.py`; `test_batch_corpus.py` loads the whole corpus at import; `test_batch_corpus_oracle.py::TestDisagreement`. |
| req-grid-batch-corpus-format-2 | Exact row sets | Implemented | `expected.live`, `tombstoned` and `absent` name exactly what exists and does not; the runner treats every other entity as must-not-move. | `runner.check`. |
| req-grid-batch-corpus-format-3 | Covers resolve | Implemented | Every `covers` entry is a requirement row in one of the five specs, checked by a scan that proves it read them. | `test_every_covers_entry_names_a_requirement_that_exists`. |
| req-grid-batch-corpus-format-4 | Pending is verified, not assumed | Implemented | A scenario carrying `pending` is an expected failure only when the checker's assertions mismatch; a passing pending scenario fails as a stale tag; a build error is a hard failure regardless. The Issue# 602 - tap gap is two such scenarios; Issue# 610 - tap two more. | `test_batch_corpus.py::test_scenario`, `::test_the_602_gap_is_a_scenario`. |
| req-grid-batch-corpus-format-5 | At least fifty | Implemented | The corpus holds at least fifty scenarios across all eight first-pass families, at least five per family (three for a family that pins one issue's shapes), and at least two per requirement it claims to cover. | `test_corpus_is_not_empty`, `test_every_family_present_with_at_least_five`, `test_coverage_matrix`. |
| req-grid-batch-corpus-format-6 | The second pass's issue shapes are scenarios | Implemented | Issues# 606, 607, 608, 351, 609, 610 and 322 - tap each have a classified scenario: the fixed ones (#606, #609) expect the fix; the open ones are verified-pending in their exact wrong shape; #322 is pinned as today's contract with the open question named. | `collision`, `atomic`, `provenance`, `hotlink`, `reload`, `replay` families; `test_the_second_pass_issue_shapes_are_scenarios`. |

### Runner Contract
----
RID: `req-grid-batch-corpus-runner`

Status: `Implemented`

#### Implementation

`tap_grid/batch_corpus/runner.py` builds the grid through the service layer (`create_node`, `create_edge`, tombstones through `delete_node` / `delete_edge_by_entity`), mints an id for every `id` name, batch name and phantom, snapshots every `Entity` (liveness, version) and every `BatchEvent` count, builds each document from the scenario and imports it through `grift_import` under the scenario's `DEBUG` (a `seed_boundary` import first goes through `strip_retired_types`, the seeding boundary's own step), learns what each committed batch's refs became from `resolved_refs`, and checks:

(a) every row the model expects exists with the expected liveness and version, a replaced node's spine name is the envelope's, and a committed batch's entity is live and its row closed;
(b) every name the model says is absent has no row, every other pre-existing entity keeps its liveness and version, and no unexpected entity appeared;
(c) the records, as **deltas** over the whole run: exactly the model's event counts per row and type (a purge takes a row's events with it, so a delta may be negative; a purge summary lands on the batch entity); and each import result's `success`, per-batch state (committed: `errors_count` 0 and a closed `Batch` row; failed: reported with errors and no row; skipped: in `skipped_batches`; refused: neither), exact issue codes with paths, exact warning codes, and `resolved_refs` for every ref that found a row.

**Three truths (second pass).** The persisted truth is read beyond liveness and version: a row's `Entity.dimensions` when the scenario declared them, every edge's `from`/`to` against the resolved ids of the names it was declared between, typed-row fields through `get_node`, and the `batch_id` stamped on the typed row — node or edge, live or tombstoned — against the batch the model says last wrote its content (a delete records its batch on the delete event and never moves the stamp; observed on the running pipeline). The API report is read for counts where a scenario spot-checks them. Provenance is read event by event: every event recorded during the run, as (entity, type, batch), must equal the events the model says each committed batch recorded — an event moved onto another committed batch is a mismatch, never "some committed batch" (Codex, PR# 637 - tap). Generated ids are symbolic: a minted ref id is checked to be a UUID version 7 distinct from every non-alias name and nothing else; a failed batch's `resolved_refs` are never read as proof of a row. The caller's document is deep-copied before the call and compared after it. After every scenario the tombstone invariant is read: no live edge has a tombstoned endpoint.

Events are compared as deltas because the test harness runs every write of a test under one ambient batch; the snapshot and delta helpers are the cascade corpus's, imported, not copied.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-batch-corpus-runner-1 | Service-layer build, public import | Implemented | Fixtures are created through the service layer and documents imported through `grift_import`; the only direct model access is reading. | `runner.build`, `runner._import`. |
| req-grid-batch-corpus-runner-2 | Three assertions | Implemented | (a), (b) and (c) above are checked for every scenario; the checker is proven to reject corrupted observations. | `runner.check`; `test_batch_corpus_checker.py` (collateral tombstone, double bump, missing row, duplicate and missing events, wrong spine name, unexpected entity, missing batch row, doctored result, wrong resolution, surviving purged row). |
| req-grid-batch-corpus-runner-3 | Refusal writes nothing | Implemented | A refused file or a failed batch proves no entity, event or batch row changed and the codes and paths match exactly. | `runner.check`; every `refused`/`failed` scenario. |
| req-grid-batch-corpus-runner-4 | No pipeline import | Implemented | The runner and tests observe only through `tap_grid.grift`, `tap_grid.services` and the models; `tap_grid.services._impl` is never imported. | The service-boundary import guard in CI. |
| req-grid-batch-corpus-runner-5 | Three truths, symbolic ids | Implemented | Persisted state (dimensions, endpoints, typed fields, typed batch stamp), the API report (counts) and provenance (per-event batch attribution) are each compared; minted ids are UUIDv7 and distinct, never compared by value; the caller's document is unchanged; the checker rejects a corruption on every layer. | `runner._check_row`, `_check_stamp`, `_check_symbolic_ids`, `event_batches_since`; `test_batch_corpus_checker.py::TestTheSecondPassRejects` (fourteen controls — a wrongly stamped live edge, a restamped tombstone, an event reassigned to the other committed batch and a rewritten edge whose other endpoint dies later among them, Codex on PR# 637 - tap). |

### Oracle Agreement
----
RID: `req-grid-batch-corpus-oracle`

Status: `Implemented`

#### Implementation

`tap_grid/batch_corpus/model_oracle.py` restates the import rules as the specs word them — file-wide preflight that writes nothing; refs resolved before any id is read; the batch id as the import identity; replace of an existing id with one bump and a spine sync without a second; the gate's mint / return / refuse with two refs on one `(type, values)` key refused (the Issue# 602 - tap ruling) and a ref that resolves to a row the batch also addresses by id or as a removal target refused against the resolved id (Issue# 606 - tap); `entity_expected_version` enforced atomically and on a missing row; dangling strict versus permissive with a tombstoned row **dangling** (ruled 2026-09-18 on Issue# 609 - tap: no live edge may point at a tombstone); removals after the upserts, edges before nodes, deletes before purges, with the policy knobs, the two events of a tombstone delete, the silent ending of incident edges and the purge's negative delta plus batch summary; per-batch atomicity with later batches still running and a rolled-back batch counting nothing (Issue# 607 - tap); the envelope authoritative for dimensions, an explicit empty map included (Issue# 608 - tap); a page's exact hotlink judged on the post-batch graph (Issue# 351 - tap); a cascade along the fixture containment edge — over the scenario's names, with no ORM. Its declaration table (`KEYED`, `UNDECLARED`, `RETIRED`) is restated, and a test proves it against the registry, so a restated fact cannot quietly go stale. At load every hand-authored expectation is compared with the model; a disagreement names both sides.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-batch-corpus-oracle-1 | Agreement at load | Implemented | A hand answer the model disagrees with fails the corpus at load, naming the disagreement. | `loader._check_against_oracle`; `test_batch_corpus_oracle.py::TestDisagreement`, `::TestRules`. |
| req-grid-batch-corpus-oracle-3 | Independent of the code under test | Implemented | The model imports nothing from TAP or Django; its declaration table is proven against the registry. | `test_the_model_imports_nothing_from_the_code_under_test`, `test_the_declaration_table_agrees_with_the_registry`. |
| req-grid-batch-corpus-oracle-4 | Metamorphic invariance where the contract permits | Implemented | Renaming every ref label consistently and adding a disconnected sentinel leave the model's answer invariant modulo ids for every non-pending scenario, and a sample holds on the database; reusing a label in another document binds afresh. Batch reordering, splitting an atomic batch and id-for-ref swaps are named as non-promises and not applied. | `tap_grid/tests/test_batch_corpus_metamorphic.py`. |

### Timing Family
----
RID: `req-grid-batch-corpus-timing`

Status: `Implemented`

#### Implementation

`tap_grid/tests/test_batch_corpus_concurrency.py` runs two writers on the real database with the cascade corpus's harness (`in_thread`, `wait_until_blocked_by`, `hold_lock_then`, `finish`): a holder takes either the identity advisory lock a ref resolution takes (`resolve_identity` inside an open transaction) or a row lock, the contending `grift_import` is observed blocked on it by pid, the holder does its work and commits, the import resumes. Cases: the same ref bundle serialised on the identity lock (the second finds the first's row); the same ref bundle in a free race (one row, one create, one update); a row tombstoned under a waiting id replace; a row bumped under a waiting versioned replace (the conflict reports the committed version); a ref that found a row retired under it. The last and the third found Issue# 611 - tap — the write pipeline's tombstone check reads before it locks, so a replace lands on a row tombstoned while it waited (version 3, content changed, an update event on a tombstone, the batch committed) — and are pending on it in that exact shape.

**Schedules (second pass; George, 2026-09-18).** `TestSchedules` runs the write × delete permutations as isolation-spec-style schedules, each docstring stating the acceptable serial outcomes: write/write on one id (two replaces, version 3, the contender's content); write then delete (the tombstone is the last write); a delete section then an upsert of the same id in two batches (the upsert is refused; Issue# 611 - tap, fixed by PR# 624 - tap); delete/delete (tombstoned exactly once; the contender's transaction-scoped target check waits on the row lock, finds the tombstone and policy-skips it — two delete events, both the holder's, the contender reporting the target skipped; observed, not assumed); edge create against endpoint delete in both orders (delete first: the edge creation blocks on the endpoint lock and is refused, Issue# 609 - tap; edge first: the delete ends the new edge); a cascade during a subtree write (refused). Before PR# 624 - tap landed, write/write on one id deadlocked — a plain replace took the typed row before the spine row while a locked-first writer took them the other way round — and the delete-first schedules wrote onto the tombstone; every verb now locks its target row first. Ref-write against id-delete and two batches creating one ref'd object are the first pass's cases. `contend(must_block=False)` is the schedule for a contender whose lock relationship is itself under test. After both writers finish every schedule asserts both invariants: `live_edges_onto_tombstones()` is empty and `rewritten_tombstones(ids)` is empty (no create/update/link event after the row's tombstone was decided — the later of `deleted_at` and the FIRST delete/unlink event that recorded it, or for an edge ended silently the first delete of either endpoint, so a later delete of the other endpoint cannot hide a write in between); the first is also an autouse fixture over the whole module. `live_edges_onto_tombstones()` reads `Edge.live_onto_tombstones()` (PR# 624 - tap), the invariant's one query.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-batch-corpus-timing-1 | Deterministic interleaving | Implemented | The block is observed by pid, every writer is joined with a timeout so a hang fails, and a known defect is accepted only in its exact shape. | `_import_blocked_by_holder`; the two pending cases recognise Issue# 611 - tap's shape and fail on any other. |
| req-grid-batch-corpus-timing-2 | Same assertions | Implemented | Each timing case asserts exact rows and versions, nothing else written, event deltas and the result shape, like a shaped scenario. | `TestTiming`, `TestSchedules`. |
| req-grid-batch-corpus-timing-3 | Schedules with named outcomes and both invariants | Implemented | Every write × delete schedule states its acceptable serial outcomes, identifies the lock it is built on, and asserts after both writers finish that no live edge has a tombstoned endpoint and no tombstone was re-written. | `TestSchedules`; `timing.live_edges_onto_tombstones`, `timing.rewritten_tombstones`, `contend(must_block=False)`. |

### Authored Datasets
----
RID: `req-grid-batch-corpus-datasets`

Status: `Implemented`

#### Implementation

Five small datasets, each a family file of its own, each adapted from a named source with TAP's expectations authored independently (the sources and revisions are in the Development section of the Scenario Format): `observations` — two observations of one thing, authored first, against an empty grid, a live row, a tombstone, a second explicit id, a removal and a stale version; `encounters` — subject / encounter / observation from the FHIR R4 transaction bundle example (shared references, a cycle, a mixed found/minted bundle, one failed conditional identity, an amendment in a second bundle); `inventory` — host / application / interface from ServiceNow IRE's payload shape (same display names on different keys, the same key on two types, a repeat from a second source, one genuinely ambiguous lookup, a tombstone beside a live row on one key; composite keys reduced to `(type, slug)`); `chain` — account / contact / case from Salesforce Composite (the chain whole, a failure at each step, the chain across two batches with the outer verdict false and the first batch counted); `sightings` — indicator / sighting from STIX 2.1 (shared nodes, a relationship crossing batches, a stale sighting removed, the feed replayed after the removal, the sighting re-observed under a fresh bundle). Two to eight entities each; neutral fixture types and `tap_web`'s `panel` / `page` only, never a consumer plugin's seeds.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-batch-corpus-datasets-1 | Five datasets, sources recorded | Implemented | The five families exist with at least three scenarios each, every family description names its source, and the spec records the source, revision and licence where one applies. | `observations`, `encounters`, `inventory`, `chain`, `sightings` `.batch.json`; `test_every_family_present_with_at_least_five`. |

### Non-Goals
----
RID: `req-grid-batch-corpus-nongoals`

Status: `Implemented`

#### Implementation

Not a plugin yet: the corpus lives in `tap_grid` and uses grid_fixtures' playground types and `tap_web`'s `panel` and `page` as its keyed types; a plugin version with its own declared types is a separate piece of work, to be spun out with the cascade corpus. Not composite keys: no core or fixture type declares a composite `NATURAL_KEY`, so the `inventory` dataset keys on `(type, slug)`; a composite-keyed fixture type is a `grid_fixtures` release (Issue# 613 - tap names it as deferred). Not force re-import or the batch-scoped sweep: those have their own tests (`test_grift.py::TestGriftForceReimport`), and Issue# 361 - tap (a strict sweep cannot retire a node whose only references are edges retired in the same version) is a sweep case that a force family would carry — out of this corpus's scope by that exclusion, named here so it is not read as covered. Not the collector's exactly-once, source precedence or global key uniqueness. Not a fuzzer, not a soak, not a performance corpus, and no property-testing dependency or generic framework: the metamorphic checks are three hand-named transformations.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-batch-corpus-nongoals-1 | Named exclusions | Implemented | The exclusions above are stated with the test or issue that owns each. | This section. |
