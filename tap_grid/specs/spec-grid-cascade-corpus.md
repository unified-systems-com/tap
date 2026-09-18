# Cascade Confirmation Corpus Specification

## Philosophy

The contained cascade (`req-grid-service-delete-cascade`) is the one write in TAP that can retire many things from one call, and its first three review rounds each found a real defect in the walk. Unit tests prove the paths their author thought of. A **corpus** is the other half: a committed set of small, eyeballable graphs, each with one delete and the outcome it must produce, run in the lanes forever, so the walk is confirmed to do exactly what it did — no more, no less — every time anything near it changes. This is how the database world holds a critical path steady: the openCypher TCK's 3,897 Gherkin scenarios, sqllogictest's known-answer files, Postgres's `foreign_key.sql` regression, Kubernetes' garbage-collector conformance suite. The shape deliberately mirrors TAP's own Gridkin corpus (`tap-plugin-gryphon-playground`, `spec-gridkin-v0.md`): scenarios are data; the expected answer is authored by a human; an independent model must agree with every hand answer at load time; and a known defect is tracked as a scenario that must fail, not papered over.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Exact | Every scenario names the exact node and edge refs that must retire; the runner proves nothing else moved — liveness AND version — and that the records say what they should |
| 2. | Eyeballable | A scenario is one JSON object a reader can check against the spec without reading Python |
| 3. | Oracle-bearing | Expected outcomes are hand-authored and cross-checked by a reference model that is a set-based reachability fixed point — no queue, no LIMIT, no SQL — and states every order-dependent answer as the set of legitimate ones |
| 4. | Honest about defects | A scenario pending a named issue is an expected failure only when it fails in the three assertions; a fixture error, a worker error or a timeout is a hard failure whatever the tag says |
| 5. | Timed as well as shaped | Interleavings that the JSON cannot express run as real two-writer cases on the real database |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-cascade-corpus-format | [Scenario Format](#scenario-format) | Implemented | The JSON shape of a `.cascade.json` family file |
| req-grid-cascade-corpus-runner | [Runner Contract](#runner-contract) | Implemented | Build through the service layer, run, assert exact retirement, no collateral, the records |
| req-grid-cascade-corpus-oracle | [Oracle Agreement](#oracle-agreement) | Implemented | A reference model agrees with every hand answer at load; order-dependent scenarios are refused |
| req-grid-cascade-corpus-timing | [Timing Family](#timing-family) | Implemented | Two-writer interleavings made deterministic with row locks |
| req-grid-cascade-corpus-nongoals | [Non-Goals](#non-goals) | Implemented | What the corpus deliberately does not do |

### Scenario Format
----
RID: `req-grid-cascade-corpus-format`

Status: `Implemented`

#### Implementation

A family file lives at `tap_grid/cascade_corpus/scenarios/<family>.cascade.json` and is validated at load against `tap_grid/cascade_corpus/cascade.schema.json` (every field described). One family per file: `depth`, `loops`, `blocks`, `limits`, `records`. A scenario has:

- `graph` — nodes by ref and type (grid_fixtures' playground vocabulary: `grid_fixtures__node/hub/leaf/cycle_node`), edges by ref from ref to ref with a `PG_*` wildcard type, `containment` per type (what `CONTAINMENT_EDGES` says for this scenario), `blocked_types` (what `INTERNAL_ONLY` says), and optional `pre_retired` refs tombstoned before the operation.
- `operation` — `delete_node` on a target ref with `cascade`, `reason`, `metadata` and `cap` (`TAP_CASCADE_MAX_CLOSURE`) passed verbatim, so a deliberately invalid value proves its refusal.
- `expected` — `outcome` (`success` | `refused`), `error_code`, **`retired_nodes` and `retired_edges` as exact sets of refs**, optional `events` spot checks a reader can verify by eye (reason, consequence_of, count), and a `note` saying why this is the right answer.
- `covers` — the requirement and acceptance-criterion ids the scenario exercises; every one must resolve to a row in `spec-grid-service-delete.md`.
- `pending` — a `owner/repo#n` the scenario waits on. While set, the scenario is built and run like any other; a mismatch in the three assertions is reported as an expected failure naming the issue, a scenario that holds fails as a stale tag, and a fixture error is a hard failure (Issue# 587 - tap).

#### Development

Scenario mining, in the Gridkin tradition of borrowing intent and never porting: the openCypher TCK's `Delete1`–`Delete6` features (delete on an already-null node; refusing to delete a connected node without `DETACH` — the mirror of TAP's rule that a reference edge is ended, never followed; `Delete6`'s insistence that side effects persist whatever shapes the result) gave the records and reference-edge families; Kubernetes' garbage-collector e2e suite (cascade versus orphan, a dependent with two live owners is kept, a dependency circle must not block, foreground deletion waits for dependents) gave the two-parent, cycle and blocked-branch cases; Postgres's `foreign_key.sql` regression (self-referential `ON DELETE CASCADE`, bug #6268; a deferred check on a tuple deleted by a rolled-back subtransaction) gave the self-loop and refusal-writes-nothing cases; LDBC SNB Interactive v2's deep deletes (`DEL1`: remove a Person, its Forums-as-moderator and all its Messages elsewhere — a cascade that crosses into other owners' content) framed the shared-child and inbound-reference cases and the discipline of validating deletes against expected result sets rather than "it returned". Datomic's `:db/isComponent` recursive retraction is the nearest declarative cousin of `CONTAINMENT_EDGES`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-cascade-corpus-format-1 | Schema-validated at load | Implemented | A family file that does not fit the schema, or a ref that does not resolve, is refused before any database work, naming the file and scenario. | `tap_grid/cascade_corpus/loader.py`; `test_cascade_corpus.py` loads the whole corpus at import. |
| req-grid-cascade-corpus-format-2 | Exact retired sets | Implemented | `expected.retired_nodes` and `retired_edges` name exactly what must retire; the runner treats everything else as must-not-move. | `runner.check` (b). |
| req-grid-cascade-corpus-format-3 | Covers resolve | Implemented | Every `covers` entry is a requirement row in `spec-grid-service-delete.md`, checked by a scan that proves it read the spec. | `test_every_covers_entry_names_a_requirement_that_exists`. |
| req-grid-cascade-corpus-format-4 | Pending is verified, not assumed | Implemented | A scenario carrying `pending` is an expected failure only when the three assertions mismatch; a passing pending scenario fails as a stale tag; setup and worker errors are hard failures regardless. | `test_cascade_corpus.py::_params`; the repeat-delete scenario pending #575. |
| req-grid-cascade-corpus-format-5 | At least fifty | Implemented | The corpus holds at least fifty scenarios across all five families, and at least two per requirement it claims to cover. | `test_corpus_is_not_empty`, `test_every_family_present`, `test_coverage_matrix`. |

### Runner Contract
----
RID: `req-grid-cascade-corpus-runner`

Status: `Implemented`

#### Implementation

`tap_grid/cascade_corpus/runner.py` builds the graph through the service layer (`create_node`, `create_edge`, pre-retirements through `delete_node`), sets the scenario's containment before the build and its blocks after it (the public create path refuses an internal-only type too, and the block under test is the delete's), snapshots every `Entity` (liveness, version) and every `BatchEvent` count, runs the operation under the scenario's cap, and checks:

(a) every expected node and edge is tombstoned;
(b) every other entity keeps its liveness and its version, and no unexpected entity appears;
(c) the records, as **deltas**: exactly one `delete` event per retired node and one `unlink` per retired edge (in a contained cascade; none for a plain delete), carrying the reason, a legitimate `consequence_of`, the root and the inherited metadata — and nothing on anything not retired. On an expected refusal: the expected error code, no entity changed, no event recorded, every batch row as it was.

Events are compared as deltas because the test harness runs every write of a test under one ambient batch; batch membership would count the graph's own creation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-cascade-corpus-runner-1 | Service-layer build | Implemented | Fixtures are created through the service layer; the only direct model access is reading. | `runner.build`. |
| req-grid-cascade-corpus-runner-2 | Three assertions | Implemented | (a), (b) and (c) above are checked for every success scenario, including the root's own record, `root_reason` on every cascaded record, and the walk's reserved keys never overridden by inherited metadata; the checker is proven to reject corrupted observations. | `runner.check`; every scenario in `test_scenario`; `test_cascade_corpus_checker.py` (collateral retirement, double bump, duplicate and missing events, wrong root_reason, missing cascade_root, wrong discoverer, dropped inherited metadata). |
| req-grid-cascade-corpus-runner-3 | Refusal writes nothing | Implemented | A refused scenario proves no entity, event or batch row changed and the error code matches. | `runner.check`; the `blocks` and `limits` families. |
| req-grid-cascade-corpus-runner-4 | No pipeline import | Implemented | The runner and tests observe only through `tap_grid.services` and the models; `tap_grid.services._impl` is never imported. | The service-boundary import guard in CI. |

### Oracle Agreement
----
RID: `req-grid-cascade-corpus-oracle`

Status: `Implemented`

#### Implementation

`tap_grid/cascade_corpus/model_oracle.py` restates the cascade rules as the spec words them — root checked first, declared containment only, discovery bounded by the cap with the root counted, a blocked node anywhere in the closure refusing the whole cascade, every incident edge ended once — as a **set-based reachability fixed point** over the scenario's declared graph, with no ORM and no queue. Everything the implementation's breadth-first walk leaves to sibling order is stated as the set of legitimate answers, derived from depth: a cascaded node's `consequence_of` may be any containing parent one level nearer the root, never a deeper one; an edge's may be either endpoint when both sit at the same depth, otherwise the shallower (Issue# 586 - tap). At load every hand-authored expectation is compared with the model; a disagreement names both sides. A scenario in which both a blocked node and an over-cap closure are reachable is refused as order-dependent — which refusal the implementation reports depends on which it meets first, and the corpus does not author coin flips.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-cascade-corpus-oracle-1 | Agreement at load | Implemented | A hand answer the model disagrees with fails the corpus at load, naming the disagreement. | `loader._check_against_oracle`; every scenario. |
| req-grid-cascade-corpus-oracle-2 | Order independence | Implemented | A scenario whose outcome depends on sibling order — a blocked node and an over-cap closure both reachable — is refused at load; every other outcome is order-free by construction, and the discoverer sets are derived from depth, not from sample orders. | `model_oracle.AmbiguousScenario`; `test_cascade_corpus_oracle.py` (three-way convergence, a deeper parent excluded, all edge permutations agree). |
| req-grid-cascade-corpus-oracle-3 | Independent of the code under test | Implemented | The model imports nothing from the service layer or the ORM. | `model_oracle.py` imports only `dataclasses`. |

### Timing Family
----
RID: `req-grid-cascade-corpus-timing`

Status: `Implemented`

#### Implementation

`tap_grid/tests/test_cascade_corpus_concurrency.py` runs two writers on the real database: each writer records its backend pid; a second connection holds `SELECT … FOR UPDATE` on a chosen node inside an open transaction; the cascade is observed — through `pg_blocking_pids`, waiter by holder, never "some backend is waiting" and never a sleep — to be blocked by exactly that holder; the holder does its work and commits; the cascade resumes. Cases: the same root deleted twice at once; a child deleted while its parent's cascade is in flight; two cascades meeting at a shared child; a child attached after discovery. A known defect is recognised by its **shape** (Issue# 587 - tap), never by "the test failed": the recognisers for Issue# 590 - tap's two shapes (a writer losing a deadlock; a row written twice) are kept as the pattern, and negative controls prove a worker exception, an unrelated error and a wrongly named holder are not accepted. #590 — found by these cases within minutes of PR# 579 - tap landing — is fixed by PR# 592 - tap (one global lock order, the closure recomputed under locks), so every case now asserts the ruled outcome in full: a child attached before the lock is retired, a child plain-deleted mid-cascade retires once with that delete's event and its own children are not cascaded (cascade-7).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-cascade-corpus-timing-1 | Deterministic interleaving | Implemented | The block is observed by pid (`pg_blocking_pids`: the waiter is blocked by the named holder), every writer is joined with a timeout so a hang fails, and a known defect is accepted only in its exact shape. | `wait_until_blocked_by`, `finish`, `lost_a_deadlock`; `TestTheHarnessItself`. |
| req-grid-cascade-corpus-timing-2 | Same three assertions | Implemented | Each timing case asserts exact retirement, no collateral (versions bump exactly once) and event deltas, like a shaped scenario. | `TestTiming`. |

### Non-Goals
----
RID: `req-grid-cascade-corpus-nongoals`

Status: `Implemented`

#### Implementation

Not a plugin yet: the corpus lives in `tap_grid` and sets `CONTAINMENT_EDGES` / `INTERNAL_ONLY` on grid_fixtures' playground types at run time; a plugin version would own types with real declarations and is a separate piece of work. Not GRIFT: only `delete_node` is exercised (cascade from GRIFT is Backlog, cascade-16). Not a fuzzer: scenarios are authored; Gridkin's metamorphic and fuzz lanes are a later borrowing. Not a performance corpus: the index-backed retrieval bound (cascade-15) has its own home.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-cascade-corpus-nongoals-1 | Named exclusions | Implemented | The four exclusions above are stated with the requirement or issue that owns each. | This section. |
