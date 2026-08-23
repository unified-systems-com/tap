# GRIFT Import Specification

## Philosophy

GRIFT defines the interchange document. The GRIFT importer specification defines how TAP consumes that document safely, consistently, and idempotently.

This separation is deliberate. The file format should stay stable and portable, while importer behavior can evolve around preflight checks, execution modes, provenance recording, and plugin-loading workflows without muddying the document contract itself.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Safe          | Validate the full file before mutation begins                   |
| 2. | Idempotent    | Skip already-imported batches by batch identity                 |
| 3. | Deterministic | Use one reference time and one preflight result per file        |
| 4. | Configurable  | Support strict and permissive dangling-edge handling            |
| 5. | Local         | Preserve GRIFT identity while recording import-side provenance  |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-import-grift-scope | [Importer Scope](#importer-scope) | Implemented | GRIFT importer responsibilities |
| req-grid-import-grift-preflight | [File Preflight](#file-preflight) | Implemented | Parse, schema validation, duplicate detection, reference analysis |
| req-grid-import-grift-time | [Reference Time](#reference-time) | Implemented | Single datetime comparison point per file |
| req-grid-import-grift-identity | [Identity And Matching](#identity-and-matching) | Implemented | Entity and batch identity rules |
| req-grid-import-grift-batch | [Batch Execution](#batch-execution) | Implemented | Per-batch transactional import behavior |
| req-grid-import-grift-removals | [Imperative Removal Execution](#imperative-removal-execution) | Implemented | Batch-level `deletes` and `purges` sections execute explicit removals after upserts and before hotlink consistency checks |
| req-grid-import-grift-removal-preflight | [Removal Preflight](#removal-preflight) | Implemented | Validate removal shape, duplicate targets, type sanity, and DEBUG gate; existence and tombstone-state checks happen inside the batch transaction |
| req-grid-import-grift-occ | [Optimistic Concurrency Enforcement](#optimistic-concurrency-enforcement) | Approved for Development | Enforce `entity_expected_version` declarations atomically inside the batch transaction; conflict aborts the batch loudly |
| req-grid-import-grift-skipped-batch-removals | [Skipped Batch Removal Warning](#skipped-batch-removal-warning) | Approved for Development | A re-imported document whose batch is skipped by `req-grid-import-grift-identity` AND contains removal sections emits a loud warning |
| req-grid-import-grift-force-reimport | [Force Re-Import](#force-re-import) | Implemented | Explicit bypass of the skip-if-exists batch guard, DEBUG-gated |
| req-grid-import-grift-batch-scoped-sweep | [Batch-Scoped Sweep](#batch-scoped-sweep) | Implemented | Tombstone orphaned entities created by a force-reimported batch; optional strict mode aborts on any guardrail miss |
| req-grid-import-grift-sweep-purge | [Sweep Purge](#sweep-purge) | Implemented | Hard-delete escalation of batch-scoped sweep, DEBUG-gated |
| req-grid-import-grift-dangling | [Dangling Edge Modes](#dangling-edge-modes) | Implemented | Strict and permissive handling |
| req-grid-import-grift-provenance | [Import-Side Provenance](#import-side-provenance) | Implemented | Local actor/history behavior |
| req-grid-import-grift-results | [Import Results](#import-results) | Implemented | Structured reporting expectations |
| req-grid-import-grift-ordering | [Deterministic Ordering And Last-Write-Wins](#deterministic-ordering-and-last-write-wins) | Implemented | Three-level ordering contract; last-write-wins per entity; lint surface |
| req-grid-import-grift-ordering-strict | [Strict-No-Overwrite Mode](#strict-no-overwrite-mode) | Backlog | Optional fail-on-pre-existing-entity mode for production/federation use |

## Importer Scope
----
RID: `req-grid-import-grift-scope`
Status: `Implemented`

The GRIFT importer is responsible for:

- reading a GRIFT document
- validating the document against the GRIFT format contract
- validating typed payloads against the local TAP model registry and field contract
- performing file-level preflight checks before mutation
- deciding batch execution behavior
- recording local import-side provenance

The GRIFT importer is not responsible for redefining the GRIFT document structure. That remains in `spec-grift-v0.md`.

## File Preflight
----
RID: `req-grid-import-grift-preflight`
Status: `Implemented`

Before any mutation begins, the importer must complete a full-file preflight pass.

### Preflight Steps

1. Parse the file as raw JSON.
2. Validate the top-level document and container structure against the GRIFT schemas.
3. Validate every batch, node, and edge wrapper shape.
4. Validate typed payloads against the local TAP model registry and field contract:
   - field shapes from `FIELD_CRUD_SCHEMA`
   - required fields from `REPLACE_REQUIRED` if declared, otherwise `CREATE_REQUIRED`
   - patch-only fields excluded
5. Detect duplicate `entity_id` values across the entire file.
6. Detect duplicate batch `entity_id` values.
7. Resolve all edge endpoint references against:
   - entities present in the same file
   - entities already present in the local grid
8. Validate optional batch-level removal sections (`deletes`, `purges`):
   - section policy values
   - required `edges` and `nodes` arrays
   - required `entity_id`, `entity_type`, and `reason` on every target
   - duplicate removal targets across all removal sections in the file
   - DEBUG-only permission for purge sections
   - (target existence, tombstone-state, and `entity_type` row sanity are NOT done at file-preflight — they are done inside each batch's transaction with row-level guarantees; see `req-grid-import-grift-removal-preflight` and `req-grid-import-grift-occ`)
9. Determine which batches already exist locally.
10. Produce one preflight result that drives the execution phase.

### Preflight Rule

No batch transaction may begin until the full file has passed preflight, except for dangling-edge handling in permissive mode, where the importer may proceed with a precomputed skip list.

### Identity Sanity

- the importer must sanity-check that the resolved local model type matches the envelope `entity_type`
- if an object payload format ever redundantly carries its own entity identity fields, those values must match the enclosing entity envelope exactly

#### Envelope/Payload Name Match

This is the first concrete application of the redundant-identity rule. The GRIFT envelope's `name` is a projection of the typed model's name field (per `spec-grid-node.md` `req-grid-node-display`: `BaseModel.get_name()` is canonical, `Entity.name` is a subordinate materialized projection). When a bundle declares both `entity.name` and the typed model payload's `name`, the two must agree exactly.

Rules:

- if `entity.name` is missing or empty in the envelope, no comparison is performed; the projection is materialized from the typed model's name on import
- if both `entity.name` and the model payload's `name` are present and non-empty, they must be string-equal after surrounding whitespace is trimmed
- mismatches emit a hard-error issue with code `envelope_payload_name_mismatch` and JSON path `$.batches[i].nodes[j].entity.name`
- mismatches accrue across the whole file: every offending node produces its own issue in the preflight report; the importer does not stop at the first hit, so a bundle author can fix all of them together
- there is no auto-align fallback. The bundle author must commit to the intended value rather than have the importer guess

This rule does not apply to edges. Edge `entity.name` is structural (the importer treats it as an authoring label) and bundles do not carry a separate edge-side name to compare against.

Future fields that are doubly declared by a model payload and the spine envelope (no current examples) should follow the same pattern with sibling codes like `envelope_payload_<field>_mismatch`.

## Reference Time
----
RID: `req-grid-import-grift-time`
Status: `Implemented`

The importer must capture one reference time at file-import start.

### Rules

- all GRIFT datetime comparisons use that single reference time
- the reference time applies to entity envelope timestamps and batch timestamps
- imported datetimes must be less than or equal to the reference time
- no explicit clock-skew allowance is defined in v0

This keeps file validation deterministic and avoids per-record timing drift during large imports.

## Identity And Matching
----
RID: `req-grid-import-grift-identity`
Status: `Implemented`

### Entity Identity

- `entity_id` is universal identity and is preserved across grids
- import matching is by `entity_id` only
- v0 performs no semantic dedupe beyond `entity_id`

### Batch Identity

- batch identity is the `entity_id` carried in `batch_entity`
- if a local object with that ID exists but is not a batch, import must fail
- if a local batch with that ID already exists, the importer assumes that batch has already been imported and skips it
- the skip behavior may be bypassed explicitly via `req-grid-import-grift-force-reimport`; default behavior remains skip-if-exists

Future versions may add content-hash or semantic batch comparison, but v0 does not.

## Batch Execution
----
RID: `req-grid-import-grift-batch`
Status: `Implemented`

Each GRIFT batch executes as its own import unit after successful file preflight.

### Execution Rules

- batches may be executed in file order or reordered internally if behavior is equivalent
- each batch should execute in its own transaction
- within a batch, nodes must be processed before edges
- skipped batches do not run any mutation logic
- node and edge mutations must route through the TAP service layer rather than direct ORM writes
- the imported GRIFT batch `batch_entity.entity_id` becomes the `batch_id` placed into `CallerContext` for the service-layer write execution
- the GRIFT batch is therefore the live service-layer batch context for the imported node and edge writes

### Spine Sync For Replaced Entities

The GRIFT envelope is authoritative for an entity's spine fields (`Entity.name`, `Entity.dimensions`) on every import. The service-layer `replace_node` verb intentionally leaves spine fields alone so callers cannot accidentally renumber entities through the model-write path; for GRIFT imports that is the wrong default, because the bundle's envelope is the bundle's declaration of truth.

After a successful node-replace operation, the importer must compare the bundle's envelope-side `name` and `dimensions` for that entity against the persisted Entity row and apply any differences. The implementation uses a direct `Entity.objects.filter(pk=...).update(...)` (not `save()`) so that a pure spine sync does not bump the entity's version counter and so the post-pass is cheap. `updated_at` is bumped explicitly when anything changes so observers can see the spine moved.

This rule applies on any import path that performs a replace, including force re-import (`req-grid-import-grift-force-reimport`). The rule does not apply to creates (the service-layer `create_node` verb already accepts the envelope's `name` and `dimensions` and writes them on the spine).

### Import Modes

GRIFT itself is neutral about create, replace, patch, or upsert semantics. The importer may expose one or more execution modes, but whichever mode it chooses must operate on the canonical GRIFT identities and validated full-object payloads produced by preflight.

## Imperative Removal Execution
----
RID: `req-grid-import-grift-removals`
Status: `Implemented`

A GRIFT batch may include explicit `deletes` and `purges` sections as defined by `req-grift-import-deletes` in `spec-grift-v0.md`. The importer must treat those sections as imperative batch operations, not as desired-state reconciliation.

### Execution Order

For each batch that executes, mutation order is:

1. create or replace declared nodes
2. create or replace declared edges
3. transaction-scoped removal-target checks (existence, type sanity, tombstone-state policy) per `req-grid-import-grift-removal-preflight`
4. tombstone `deletes.edges` (each verb call carries `entity_expected_version` when declared)
5. tombstone `deletes.nodes` (each verb call carries `entity_expected_version` when declared)
6. hard-delete `purges.edges` (each verb call carries `entity_expected_version` when declared)
7. hard-delete `purges.nodes` (each verb call carries `entity_expected_version` when declared)
8. batch-scoped sweep, when force re-importing (`req-grid-import-grift-batch-scoped-sweep`)
9. pre-commit consistency checks, including hotlink validation

Edge removals run before node removals inside each section. This makes relationship removal explicit and lets node deletes operate on the intended post-edge-removal graph.

Steps 4–7 are performed by the service-layer delete and purge verbs. Each verb performs its own atomic check-and-mutate so that optimistic-concurrency `entity_expected_version` declarations (`req-grid-import-grift-occ`) have a zero-width race window. A version-conflict or other verb-level failure on any removal aborts the batch transaction; every upsert, delete, and purge in this batch rolls back.

Delete operations must be appended to the same service-layer `write_batch()` execution as node and edge upserts, so the pre-commit consistency phase sees the final post-delete graph. Delete operations use the normal service-layer delete verbs:

- `deletes.edges[]` routes to `delete_edge_by_entity` / `delete_edge`
- `deletes.nodes[]` routes to `delete_node`

Purge operations route through DEBUG-only service-layer purge primitives:

- `purges.edges[]` routes to `purge_edge`
- `purges.nodes[]` routes to `purge_node`

If purge operations cannot share the same `write_batch()` machinery as tombstone deletes, the importer must still execute them inside the same per-batch database transaction and before the batch-scoped sweep and pre-commit consistency phase. A failure in any purge operation rolls back the full batch, including earlier upserts and tombstone deletes.

### Provenance And Reason Capture

Every removal target's `reason` must be preserved in batch-scoped trace data.

For tombstone deletes, the target-level `BatchEvent` metadata should include at least:

```json
{
  "grift_operation": "delete",
  "reason": "No longer part of this seed set."
}
```

For purges, target-level rows may be removed as part of the purge contract, so the importer must also emit a surviving batch-level summary event against the batch entity. That summary should include:

- operation kind: `delete` or `purge`
- target `entity_id`
- target `entity_type`
- target kind: `edge` or `node`
- `reason`
- outcome: `applied`, `missing`, `already_tombstoned`, `warned`, or `ignored`

The summary event may reuse a dedicated `BatchEventType` value if one exists, or use an equivalently structured event record. The trace must survive purges.

### Non-Goals

- The importer does not infer deletion from objects absent from `nodes` or `edges`.
- The importer does not delete by query, type, dimension, or batch ownership under this requirement.
- The importer does not perform authoritative upstream reconciliation. AWS/account-style trimming is future desired-state machinery, not this feature.

## Removal Preflight
----
RID: `req-grid-import-grift-removal-preflight`
Status: `Implemented`

Removal preflight is split into two phases by **what it can check without reading mutable database state**.

File-level preflight checks shape, policy enum values, duplicate targets across the document, and the DEBUG gate. These checks are pure functions of the document plus immutable settings; they do not require database reads against rows that might change before execution.

Target-existence, entity-type row sanity, tombstone-state policy application, and version-conflict detection happen **inside the batch's `transaction.atomic()` block**, immediately before that batch's removal verbs run. This guarantees the policy decision is made against the same database snapshot the mutation will operate on, closing the race window that any read-then-act file-preflight design would leave open. See `req-grid-import-grift-occ` for the version-conflict half of that contract.

### File-Level Preflight Checks

The importer must enforce the GRIFT schema requirements for removal sections at file-preflight time:

- section-level policy fields are required
- `deletes.on_missing` is one of `error`, `warn`, `ignore`
- `deletes.on_tombstoned` is one of `error`, `warn`, `ignore`
- `purges.on_missing` is one of `error`, `warn`, `ignore`
- `edges` and `nodes` arrays are required inside each present section
- every target requires `entity_id`, `entity_type`, and non-empty `reason`
- `entity_expected_version`, when present, is a positive integer (minimum 1; `Entity.version` starts at 1, so 0 is not a valid expected value)
- item-level policy overrides are invalid in v0

### Duplicate Targets

The same `entity_id` may not appear more than once across all removal sections in the same GRIFT document. This includes:

- duplicate entries inside one `deletes.edges` / `deletes.nodes` / `purges.edges` / `purges.nodes` array
- the same target appearing in both delete and purge sections
- the same target appearing as both a node and an edge removal target

Duplicate removal targets are hard file-preflight errors with a stable code such as `duplicate_removal_target`.

### Upsert / Removal Cross-Section Duplicates

An `entity_id` that appears as an upsert envelope (in any batch's `nodes` or `edges` array) AND as a removal target (in any batch's `deletes.*` or `purges.*` array) in the same GRIFT document is a hard file-preflight error with the code `entity_id_in_upsert_and_removal`. The combination is technically order-deterministic — upserts run before removals within each batch — but reads as an authoring mistake (you wrote the entity twice; the second write erases the first) and almost always indicates that one of the two declarations was a copy-paste error or a wrong file. Forcing it loud at preflight matches the rest of GRIFT's strict-by-default posture; an author who genuinely wants to upsert-then-remove can do so by splitting the work into two separate GRIFT documents.

### Purge Gate

Any present `purges` section with at least one declared target is permitted if and only if Django `DEBUG` is `True`. When `DEBUG` is `False`, file-preflight emits a hard error such as `grift_purge_refused_production`. There is no command-line override, settings override, or environment-variable override.

The gate fires on declaration, not on execution-outcome. A `purges` section with a single target on a `DEBUG=False` host is refused at file-preflight even if that target turns out to be `on_missing`'d at execution. This makes the DEBUG gate a property of *what the document asks for*, not *what ends up running*, which is what an operator reviewing a bundle wants to see.

### Transaction-Scoped Target Checks

Inside each batch's `transaction.atomic()` block, **after** node and edge upserts complete and **before** removal verbs run, the importer performs per-target state checks. The checks must run against a **row-locked** view of each target's Entity row — Postgres's default isolation level (READ COMMITTED) does not by itself prevent another transaction from mutating the target between the check and the verb call, so the importer takes a `SELECT … FOR UPDATE` on each target's Entity row (or equivalent row-level lock) at the start of this phase and holds it until the batch commits or rolls back. This guarantees the policy decision and the subsequent verb call see the same row state.

With the lock held, for each removal target the importer resolves the local Entity row by `entity_id`.

If the target is missing:

- `on_missing == "error"` aborts the batch with a `removal_target_missing` issue
- `on_missing == "warn"` records a warning and skips this target
- `on_missing == "ignore"` records no issue and skips this target

If the target exists but its local `entity_type` does not match the declared `entity_type`, the batch aborts with a `removal_entity_type_mismatch` issue. Policy knobs do not soften type mismatch.

If a target is listed under `edges`, its local and declared `entity_type` must be `"edge"`. If a target is listed under `nodes`, its local and declared `entity_type` must not be `"edge"`.

For tombstone deletes, if the target already has `Entity.deleted_at` set:

- `on_tombstoned == "error"` aborts the batch with a `removal_target_tombstoned` issue
- `on_tombstoned == "warn"` records a warning and skips this target
- `on_tombstoned == "ignore"` records no issue and skips this target

For purge, tombstoned-but-present targets are valid purge targets. There is no `purges.on_tombstoned` setting.

Targets that pass these checks proceed to their removal verb, which carries `entity_expected_version` (when declared) through to the service-layer Entity-row guard that performs the delete or purge. The version check happens inside that verb; see `req-grid-import-grift-occ` and `req-grid-service-batch-occ`.

### Reporting

The import result should expose removal counts and issues separately enough that callers can distinguish removal outcomes from upsert outcomes.

Recommended count fields:

- `entities_deleted`
- `edges_deleted`
- `nodes_deleted`
- `entities_purged`
- `edges_purged`
- `nodes_purged`
- `removals_skipped`

Recommended issue codes:

- `duplicate_removal_target`
- `entity_id_in_upsert_and_removal`
- `removal_target_missing`
- `removal_entity_type_mismatch`
- `removal_target_tombstoned`
- `grift_purge_refused_production`
- `removal_execution_failed`
- `entity_version_conflict` — see `req-grid-import-grift-occ`

## Optimistic Concurrency Enforcement
----
RID: `req-grid-import-grift-occ`
Status: `Approved for Development`

The importer enforces the GRIFT optimistic-concurrency contract (`req-grift-concurrency-version` in `spec-grift-v0.md`) at the database-mutation boundary. A target that declares `entity_expected_version` must observe that version at the moment the mutation runs; otherwise the entire batch aborts and rolls back atomically.

### What Gets Checked

OCC enforcement covers exactly the targets described in `req-grift-concurrency-version`:

- node / edge envelopes whose `entity_id` already exists locally and therefore drive a replace
- every target in `deletes.edges` / `deletes.nodes`
- every target in `purges.edges` / `purges.nodes`

Targets that omit `entity_expected_version` are processed without a version check. Targets that include `entity_expected_version` are processed with the check. Mixed bundles are supported on a per-target basis.

### Where The Check Runs

The check is delegated to the service layer. Each affected verb accepts `entity_expected_version` as a keyword argument; the verb enforces the check via a single atomic guard on the `Entity` row (a conditional `UPDATE` carrying the version predicate, or a `SELECT … FOR UPDATE` followed by a compare-and-act, both inside the verb's transaction). Exactly one `Entity.version` increment is recorded per successful operation; downstream typed-model save, history, FLIP, and spine sync run inside the same guarded transaction. See `req-grid-service-batch-occ` in `spec-grid-service-batch.md` and the per-verb specifications in `spec-grid-service-write.md` and `spec-grid-service-delete.md`.

The importer does not perform a separate read-then-check; it passes `entity_expected_version` straight through to the verb. If the verb reports a version conflict, the importer translates it into a GRIFT issue and bails.

### Conflict Semantics

A version conflict is fatal to the batch. There is no `on_entity_version_conflict` policy:

- the batch's atomic transaction rolls back
- every upsert, delete, and purge in this batch is undone
- a `entity_version_conflict` issue is emitted with the conflict details
- the batch's outcome is reported as failed

The conflict issue must include enough information for the sender to recover:

- `entity_id`
- `entity_type`
- `entity_expected_version` (from the document)
- `actual_entity_version` (from the local Entity row at the moment the mutation was attempted)
- `path` (JSONPath to the offending target within the document)
- `operation` (the verb the importer was about to run: `replace_node`, `delete_node`, etc.)

Multiple in-flight verbs may all carry `entity_expected_version`, but the importer fails on the first conflict it encounters and surfaces only that one in v0. The implementation may surface every detected conflict in a future revision; the spec does not require it.

### Interaction With Removal Policy Knobs

`entity_expected_version` is independent of `on_missing` and `on_tombstoned`:

- if a target is `on_missing="ignore"` skipped at the transaction-scoped check, the version check is also skipped (the verb never runs)
- if a target is `on_tombstoned="warn"` skipped, the version check is also skipped
- if a target passes the existence and tombstone-state checks, the version check runs as described above

This ordering means a target declared with `on_missing="ignore"` and a stale `entity_expected_version` does not produce a spurious conflict for a target that wasn't going to be modified anyway.

### Client Guidance

Senders that engage OCC are responsible for retry-on-conflict. The recommended pattern is:

1. capture local `Entity.version` for every target before authoring the bundle
2. submit the bundle
3. on `entity_version_conflict`:
   - re-read the affected entities
   - re-evaluate the sender's intent in light of the new state
   - re-author and resubmit, or surface the conflict to the operator if the new state changes the answer

A future TAP client library is expected to wrap this loop with exponential-backoff retries on conflicts, mirroring `client-go`'s `RetryOnConflict`, asyncpg / SQLAlchemy retry-on-`40001`, and CockroachDB's documented retry loop. The library is not part of this requirement; the contract is documented here so future libraries converge on the same shape.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-import-grift-occ-1 | Atomic Check-And-Mutate | Approved for Development | The version check is performed atomically with the mutation by the service-layer verb, not as a separate read-then-act step in the importer. | Race window is zero. |
| req-grid-import-grift-occ-2 | Conflict Aborts The Batch | Approved for Development | Any `entity_version_conflict` from any in-scope target rolls the batch back atomically. | All-or-nothing with the surrounding `transaction.atomic()`. |
| req-grid-import-grift-occ-3 | Diagnostic Detail Included | Approved for Development | The `entity_version_conflict` issue includes `entity_id`, `entity_type`, `entity_expected_version`, `actual_entity_version`, `path`, and `operation`. | |
| req-grid-import-grift-occ-4 | No Policy Knob | Approved for Development | The file format and importer do not expose a way to soften a version conflict; it always fails loud. | |
| req-grid-import-grift-occ-5 | Mixed Bundles Allowed | Approved for Development | A batch may freely combine targets with and without `entity_expected_version`; each is enforced independently. | |
| req-grid-import-grift-occ-6 | Policy-Skipped Targets Bypass Version Check | Approved for Development | A target that the transaction-scoped check skips (e.g. `on_missing="ignore"`) does not produce a version-conflict issue even if its `entity_expected_version` would have mismatched. | |
| req-grid-import-grift-occ-7 | Conflict-Resolution Is Client Responsibility | Approved for Development | The importer does not retry on conflict. Senders own the retry-or-surface decision. | A future client library is expected to wrap retry-with-backoff. |


## Skipped Batch Removal Warning
----
RID: `req-grid-import-grift-skipped-batch-removals`
Status: `Approved for Development`

A batch whose `batch_entity_id` already exists locally is skipped by `req-grid-import-grift-identity`. The existing visibility contract (`req-grid-import-grift-ordering-6`) requires a `[skip]` log line and a `result.skipped_batches[]` entry with the explicit `--force-batches` recipe. That is sufficient when the skipped batch contained only upserts: the author can re-run with `--force-batches` if they meant to re-apply.

Skipped batches that contain removal sections are a higher-blast-radius case. A missed upsert can be recovered by re-authoring or re-running; a missed removal leaves stale state in the grid with no visible signal that anything was supposed to be different. The author of the bundle has to remember the document contained `deletes` or `purges` to even think to check `skipped_batches[]`.

### Required Behavior

When a batch is skipped by the skip-if-exists rule AND that batch's container in the incoming document includes either a non-empty `deletes` section or a non-empty `purges` section, the importer must:

- emit a warning-level log line distinct from the standard `[skip]` line, identifying the batch and naming the removal counts
- include a `skipped_batch_had_removals` warning in `result.warnings[]`, with the offending batch's `batch_entity_id`, the counts of declared removal targets by section, and the same `--force-batches=<id>` recipe so the operator can re-run loudly

The warning fires on declaration of removal targets, not on whether those targets would have removed anything. An author who writes `deletes` with five targets meant for those five removals to fire; if the batch is skipped, all five missed.

A skipped batch whose removal sections are entirely empty (`deletes` and `purges` both present-but-empty, or both absent) does not require this extra warning — the conventional skip line covers it.

### Issue Shape

Recommended issue code: `skipped_batch_had_removals`.

Recommended payload fields:

- `batch_entity_id`
- `deletes_edges_count`
- `deletes_nodes_count`
- `purges_edges_count`
- `purges_nodes_count`
- `force_recipe` — the literal `--force-batches=<id>` string that would re-run the batch

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-import-grift-skipped-batch-removals-1 | Warning On Skipped Batch With Removals | Approved for Development | A skipped batch whose document container includes one or more non-empty removal sections produces a `skipped_batch_had_removals` warning. | |
| req-grid-import-grift-skipped-batch-removals-2 | Empty Sections Do Not Trigger | Approved for Development | A skipped batch with no declared removal targets does not produce this warning. | The standard skip log line is sufficient. |
| req-grid-import-grift-skipped-batch-removals-3 | Recipe Included | Approved for Development | The warning payload includes the literal `--force-batches=<id>` invocation that would re-run the batch. | |
| req-grid-import-grift-skipped-batch-removals-4 | Separate From Standard Skip Line | Approved for Development | The warning is emitted in addition to, not instead of, the existing `[skip]` log line and `skipped_batches[]` entry from `req-grid-import-grift-ordering-6`. | |


## Deterministic Ordering And Last-Write-Wins
----
RID: `req-grid-import-grift-ordering`
Status: `Implemented`

GRIFT execution is deterministic by declaration. The same set of grift bundles imported on the same plugin set produces the same final graph, regardless of when the import runs or which session it runs in.

### The Three Ordering Levels

GRIFT execution traverses three nested ordering scopes. The contract at each level is *declaration order*:

1. **Plugin order** — the order plugins appear in `INSTALLED_APPS` is the contract. Each TAP plugin's grift bundles are imported in the loop iteration where its `AppConfig` is processed, so the plugin order in `INSTALLED_APPS` determines the relative execution order of every grift bundle owned by different plugins. (Future work: `req-dev-multisession-spawn-script` may grow declared `dependencies = [...]` in `tap-plugin.toml` so the order can be derived from a topological sort rather than a developer-maintained list. For now, `INSTALLED_APPS` order *is* the dependency order, and changes to it are real semantic changes — review accordingly.)
2. **Manifest bundle order** — within a plugin, the order of entries in the `[grift]` table of `tap-plugin.toml` is the contract. Python's `tomllib` preserves declaration order; the importer iterates that order without re-sorting.
3. **In-file batch order** — within a single grift document, the `batches` array order is the contract. Within a single batch, `nodes` are processed before `edges`, and within each list the array order is preserved.

These three levels nest: plugin A's bundle Z executes after plugin A's bundle Y, which executes after plugin (A-1)'s last bundle. The same logic applies recursively to batches inside a bundle.

### Per-Entity Last-Write-Wins

Within the deterministic order above, the importer is **upsert-by-default at the per-entity level**:

- When a `nodes[]` or `edges[]` element declares an `entity_id` that already exists in the local grid, the importer routes the operation through the service-layer `replace_node` (or `replace_edge`) verb. The latest declaration wins.
- When a batch declares an `entity_id` that does not yet exist, the importer routes through `create_node` (or `create_edge`).

This is distinct from the *batch-level* skip-if-exists guard documented in [Identity And Matching](#identity-and-matching). The batch guard is the file-level idempotency contract: if a `batch_entity.entity_id` has been seen before, the entire batch is skipped (an explicit `--force-batches` opt-in is the bypass). Only batches that *do* execute apply per-entity last-write-wins.

The combined semantics:

| Scenario | Behavior |
| --- | --- |
| Same `batch_entity_id` re-imported with different content | **Skipped** — explicit `--force-batches` required to re-execute |
| Different `batch_entity_id`s declaring the same `entity_id` | **Last-batch-wins** — the second batch's `replace_node` overrides the first batch's `create_node` |
| Same plugin, two bundles, same `entity_id` | **Last-bundle-wins by manifest order** |
| Two plugins, same `entity_id` | **Last-plugin-wins by `INSTALLED_APPS` order** |

### Visibility Requirements

Last-write-wins is a useful tool, but a silent one is a footgun. The importer must surface every override so a developer can confirm intent:

- **Per-entity upsert log line** — for every node or edge whose `entity_id` already existed in the grid and was replaced, the import command emits a structured `[upsert]` line with kind, entity_type, entity_id, and envelope name. The `GriftImportedBatch` result carries an `upserted_entities` list of `GriftUpsertedEntity` records to support programmatic consumers.
- **Skipped-batch log line** — when a batch is skipped because its `batch_entity_id` already exists, the import command emits a `[skip]` line that includes the `--force-batches=<id>` invocation that would re-run it. The `GriftImportResult.skipped_batches` list carries the same information.
- **Lint mode** (`--lint`) — a non-mutating, non-DB scan that reads every selected plugin's bundles in declared order, groups by `entity_id`, and reports any id that appears in more than one location. Used as a CI guard and as a "do I really mean to override this?" check during development. Exits non-zero when duplicates are found.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-import-grift-ordering-1 | Plugin order is `INSTALLED_APPS` order | Implemented | Bundles owned by plugin A always execute before bundles owned by plugin B when A appears before B in `INSTALLED_APPS`. | |
| req-grid-import-grift-ordering-2 | Manifest order preserved | Implemented | Bundles within a plugin execute in `tap-plugin.toml` `[grift]` declaration order. | |
| req-grid-import-grift-ordering-3 | In-file batch order preserved | Implemented | Batches execute in `batches[]` array order; nodes-before-edges within each batch. | |
| req-grid-import-grift-ordering-4 | Per-entity last-write-wins | Implemented | When two batches declare the same `entity_id`, the later one's content is the persisted state via `replace_node`/`replace_edge`. | |
| req-grid-import-grift-ordering-5 | Per-entity upsert visibility | Implemented | Each entity replacement emits an `[upsert]` log line and is recorded on `GriftImportedBatch.upserted_entities`. | |
| req-grid-import-grift-ordering-6 | Skipped-batch visibility | Implemented | Each skipped batch emits a `[skip]` log line that includes the explicit `--force-batches` recipe to re-run it. | |
| req-grid-import-grift-ordering-7 | Lint mode | Implemented | `--lint` scans all selected bundles, reports cross-bundle `entity_id` duplicates, exits non-zero on any duplicate. | |

## Strict-No-Overwrite Mode
----
RID: `req-grid-import-grift-ordering-strict`
Status: `Backlog`

A future opt-in mode that fails the import when any node or edge being processed declares an `entity_id` that already exists in the grid. Inverts the per-entity last-write-wins default for environments where overwrites should be a hard error rather than a soft override.

### Motivation

Last-write-wins is the right default for development seeding: edit a file, re-run, see the change. It is the wrong default for two future scenarios:

- **Production-like seeding** — a one-shot `import_plugin_grift` run on a non-development environment, where any pre-existing entity probably indicates a misconfiguration (e.g. running a seed that was already applied) and silent overrides are dangerous.
- **Federated imports** — when GRIFT bundles arrive from another grid (or another tenant) and the local grid is the canonical owner, an inbound bundle that would silently overwrite local state should fail with a clear error rather than apply.

### Shape

The exact spelling is open. Two reasonable forms:

- **Command flag** — `--strict` (or `--mode=strict`) at invocation time. Cheap to add; appropriate for ad-hoc use.
- **Batch-level field** — a `mode` value in the batch envelope or document metadata that declares the bundle's intent. Lets the *file* assert "this batch must not overwrite anything" so the contract travels with the data — useful for federation, where the receiving grid otherwise has no signal about the bundle's intent.

A combined form is plausible: command flag overrides batch field; batch field overrides default. Defer the choice until the use case lands.

### Out Of Scope

- Federation transport, authentication, or routing — this requirement is about local enforcement only.
- Production deployment policy. The importer's `DEBUG`-gated escape valves (`req-grid-import-grift-force-reimport`, `req-grid-import-grift-sweep-purge`) remain the operative control for production hygiene.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-import-grift-ordering-strict-1 | Strict mode rejects overwrites | Backlog | When strict mode is engaged and any node/edge `entity_id` already exists, the import fails before any writes and rolls back. | |
| req-grid-import-grift-ordering-strict-2 | Per-entity report on failure | Backlog | The error report names every offending `entity_id` (not just the first hit) so a developer can fix all of them in one pass. | |

## Force Re-Import
----
RID: `req-grid-import-grift-force-reimport`
Status: `Implemented`

The importer must expose an explicit, opt-in path to re-execute a batch whose `batch_entity.entity_id` is already present locally. Default behavior (skip-if-exists, per `req-grid-import-grift-identity`) is unchanged.

This is the escape valve promised by *"Future versions may add content-hash or semantic batch comparison, but v0 does not."* It exists for development iteration on GRIFT files — editing content, re-running the importer, and seeing the new state reflected without generating a fresh `batch_entity.entity_id` and bumping plugin contracts.

### Invocation

- The command line or programmatic API must accept a `--force-batches=<batch_entity_id>[,<batch_entity_id>...]` argument. No flag is permitted to force an entire file or plugin in one call.
- The argument names `batch_entity` identities explicitly. Anything not in the list follows normal skip-if-exists semantics.
- An empty or missing `--force-batches` argument means the feature is inactive; the importer behaves as today.

### Execution

- For each named batch, the importer bypasses the skip check and runs the full batch execution path (`req-grid-import-grift-batch`).
- The batch's node and edge writes go through the service layer with `CallerContext.batch_id = batch_entity.entity_id` — the **original** id, unchanged. Force re-import does not mint a new batch; it re-applies the existing one.
- Upsert semantics apply: existing nodes with matching `entity_id` are updated; new nodes introduced in the revised content are created; unchanged nodes are no-ops.
- Removal sections are re-applied. `deletes` and `purges` declared in the revised batch run on every force re-import in their normal execution position (`req-grid-import-grift-removals` execution order). Their idempotency properties under repeated application come from the section policy knobs (`on_missing`, `on_tombstoned`) and from `entity_expected_version` declarations; the importer itself does not deduplicate removals across force re-imports.
- Sweep removals — entities that existed under this batch previously but are absent from the revised content — are NOT handled by this requirement. Sweep behavior is defined by `req-grid-import-grift-batch-scoped-sweep`; explicit `deletes` / `purges` sections are defined separately by `req-grid-import-grift-removals`. When both apply, explicit removals execute first and sweep skips targets already tombstoned by them (per `req-grid-import-grift-batch-scoped-sweep`).

### Environment Gate

**Invariant:** Force re-import is permitted if and only if Django's `DEBUG` setting is `True` at the moment of invocation. There is no alternate flag, override, settings key, environment variable, or command-line argument that enables it in any other configuration. This invariant is binding on every requirement that builds on force re-import (`req-grid-import-grift-batch-scoped-sweep`, `req-grid-import-grift-sweep-purge`).

- When `DEBUG` is `False`, the importer must refuse the invocation with a dedicated error code (e.g. `force_reimport_refused_production`) distinct from "batch not found" or "invalid argument" errors, so the operator can see exactly why it was rejected.
- The gate is not a security boundary — an operator who can flip `DEBUG` can already read and write the database directly. The gate exists solely to prevent accidental use of dev ergonomics in production deploy scripts. It is not a substitute for deployment discipline and must not be treated as one.
- Future proposals to relax or conditionally bypass this gate (e.g. "staging environments should allow force re-import") must land as explicit, named requirements. This requirement does not anticipate such cases.

### Audit Trail

- Each force re-import must emit a `BatchEvent` (or equivalently-structured event record) of type `FORCE_REIMPORT` against the batch, with:
  - timestamp of the re-import
  - actor (per `req-grid-import-grift-provenance`)
  - count of nodes updated, nodes created, edges updated, edges created, entities swept (per `req-grid-import-grift-batch-scoped-sweep` when that applies)
- The original ingestion's batch events remain untouched. The audit reads as a sequence: initial ingest → force re-import(s) → further activity.
- A batch that has been force-reimported is still the same batch entity. It retains its original `entity_id`, batch metadata, and service-layer ownership semantics.

### Non-Goals

- Force re-import does not compare content hashes, compute semantic diffs, or flag drift proactively. It runs exactly when asked, and only when asked.
- It does not bypass preflight validation. A force-reimported batch still passes through schema validation, reference analysis, and dangling-edge checks.

## Batch-Scoped Sweep
----
RID: `req-grid-import-grift-batch-scoped-sweep`
Status: `Implemented`

When a batch is force re-imported (`req-grid-import-grift-force-reimport`), the revised content may omit nodes or edges that the original ingestion created. The sweep detects those orphans and tombstones them via the service-layer delete path, bounded strictly to entities this batch originally created.

### Ordering Relative To Explicit Removals

Explicit removal sections (`req-grid-import-grift-removals`) execute **before** the sweep within the same batch transaction. The execution sequence is:

1. node and edge upserts
2. explicit `deletes` and `purges`
3. batch-scoped sweep
4. pre-commit consistency phase (hotlinks, etc.)

A candidate entity that has already been tombstoned by an explicit `deletes` target in this same batch is *not* a sweep candidate — the sweep skips already-tombstoned entities by design (it tombstones via the service-layer delete path, which is idempotent against already-tombstoned targets). This avoids double-effort and keeps the audit trail attributable to the explicit removal that fired first.

### Sweep Candidates

A candidate for sweep is an entity meeting all of:

- the entity's **creation history row** (first historical record) carries `batch_id == <the batch being force-reimported>`
- the entity's current `entity_id` does not appear in the revised batch's node or edge set
- the entity is not already tombstoned (whether by this batch's explicit `deletes` or by prior history)

Candidates are computed after the revised batch's upserts have been staged AND after this batch's explicit removal sections have run, so the candidate set reflects the post-explicit-removal graph. This ordering means a bundle author may use explicit `deletes` for entities they want to name explicitly (with attached `reason`) and rely on the sweep for the longer tail of entities the batch originally created.

### Guardrails

A candidate is only swept if **both** guardrails pass:

**Guardrail A — Ownership**

No history row exists for this entity with `batch_id != <this batch>`. If any other batch has written to the entity (create, update, or delete), skip it. The entity has left this batch's exclusive ownership and the sweep must not reclaim it.

**Guardrail B — Referential Integrity**

After the sweep's proposed deletions are applied, no edge exists that is connected to this entity — in either direction. An edge survives the sweep and references the candidate if:

- the edge exists in the current graph AND is not itself being swept, OR
- the edge is newly created by the revised batch content and points at this candidate (a content bug in the revision — preflight should catch it, but the guardrail provides a second line of defense)

If any such edge survives, skip the candidate. The entity remains structurally connected to the post-apply graph and must not be removed.

The two guardrails are independent. A candidate skipped by A is reported under reason code `sweep_skipped_external_write`. A candidate skipped by B is reported under `sweep_skipped_referenced`. A candidate skipped by both is reported under A (ownership is the stronger signal).

### Default Action

Swept entities are tombstoned via the service-layer delete path (`Entity.deleted_at`, with cascade to connected edges per the standard tombstone semantics). History rows are preserved. Edges attached to the swept entity that originated in this same batch are tombstoned in the cascade.

### Strict Mode

The importer must expose an optional `--sweep-strict` flag that changes when the sweep executes, not what it does. In strict mode, **any candidate that would fail either guardrail aborts the entire force re-import before any writes occur**.

**Invocation:**

- `--sweep-strict` is only meaningful alongside `--force-batches`. Passing it without force re-import is an invocation error.
- Orthogonal to `--purge` — the two flags combine cleanly. `--force-batches=<id> --sweep-strict --purge` means *"hard-delete the orphans, but only if I can do so cleanly."*
- Inherits the `DEBUG=True` invariant from `req-grid-import-grift-force-reimport`; no additional gate required.

**Execution:**

- Sweep candidates are computed and guardrails evaluated as usual.
- If **any** candidate fails Guardrail A or Guardrail B, the entire force re-import aborts. No node upserts, no edge upserts, no tombstones, no purges are written. The database state is unchanged.
- If all candidates pass both guardrails (or if there are no candidates), the force re-import proceeds exactly as it would have without `--sweep-strict`.
- The abort surfaces as a dedicated error code (e.g. `sweep_strict_aborted`) with a structured report of every candidate that would have been skipped and its reason.

**Rationale:**

Default sweep behavior (skip-with-report) favors completing the operation and surfacing the skips afterward. That's the right default for normal iteration. Strict mode inverts the tradeoff: when the operator expects a clean sweep ("this batch is fully mine, nothing external has touched it"), a silent partial success is worse than no change at all, because it leaves the grid in an ambiguous half-applied state. Strict mode refuses to create that state and forces the operator to resolve ownership or reference issues first.

### Reporting

The importer's force-reimport report must include:

- `swept_entities`: list of `{entity_id, entity_type, reason: "orphaned"}` objects for entities tombstoned
- `sweep_skipped`: list of `{entity_id, entity_type, reason}` objects for candidates that failed a guardrail, with reason codes from the guardrail text above
- `sweep_strict_aborted`: boolean; `true` if `--sweep-strict` was set and the run aborted due to skipped candidates. When `true`, `swept_entities` must be empty and `sweep_skipped` carries the full list of offending candidates.

### Non-Goals

- The sweep does not touch entities whose creation history is not owned by this batch. Dimensional authority, cross-plugin cleanup, and importer-declared ownership over a dimension are out of scope and tracked as a future concern (see *Future* below).
- The sweep does not re-tombstone already-tombstoned entities, and does not restore tombstoned entities.
- The sweep does not observe edge-only creation records. Edges created by this batch that point at entities owned by other batches stay put unless the edge itself is absent from the revised content; in that case the edge is an ordinary upsert-delete target and handled by batch-standard cascade behavior, not by the sweep.

### Future

Authoritative-importer semantics — "this importer owns dimension X; sweep anything present in X not in this import" — is a related but distinct concern. The common case (a recurring AWS pull that wants its absences honored as deletions) is expected to be solvable by using a stable `batch_entity.entity_id` per source and force re-importing on each pull: the batch-scoped sweep then naturally handles absences. If a use case emerges that cannot be expressed this way, a separate authoritative-importer extension requirement can land (RID minted then).

## Sweep Purge
----
RID: `req-grid-import-grift-sweep-purge`
Status: `Implemented`

An optional escalation of `req-grid-import-grift-batch-scoped-sweep` that replaces tombstone with hard-delete for swept entities. Intended for rapid development iteration where accumulated tombstones from ephemeral grift-file edits would obscure rather than document the grid's durable state.

### Invocation

- The command line or programmatic API must accept a `--purge` flag alongside `--force-batches`. `--purge` without `--force-batches` is an invocation error.
- `--purge` applies to the entire force re-import invocation. There is no per-batch toggle; the operator decides purge-or-tombstone at the command level and it applies to every swept entity in the run.

### Environment Gate

**Invariant:** `--purge` is permitted if and only if Django's `DEBUG` setting is `True` at the moment of invocation. This is the same binding invariant as `req-grid-import-grift-force-reimport`'s environment gate, applied independently here so there is no ambiguity when reading this requirement in isolation. There is no alternate flag, override, settings key, environment variable, or command-line argument that enables `--purge` in any other configuration.

- When `DEBUG` is `False`, passing `--purge` must surface a dedicated error code (e.g. `sweep_purge_refused_production`) distinct from other refusal or invocation errors.
- The grid invariant that "history is preserved" is protected by this gate. `--purge` is the single exception to that invariant and is bounded by this requirement alone; no other requirement may delegate hard-delete behavior to this one without its own explicit gate.
- Future proposals to relax this gate must land as explicit, named requirements. This requirement does not anticipate such cases.

### Guardrails

The purge uses **exactly the same guardrails** as the default sweep (Ownership and Referential Integrity) and **exactly the same strict-mode semantics** if `--sweep-strict` is also set. Purge does not relax or bypass either guardrail, and does not alter strict-mode's abort behavior. A candidate that fails a guardrail is skipped in both modes with the same reason code; if `--sweep-strict` and `--purge` are both set and any candidate fails, the entire run aborts before any writes.

### Hard-Delete Action

For each swept candidate, when `--purge` is set:

- The entity row is hard-deleted from the database (not tombstoned).
- Historical records for this entity with `batch_id == <the force-reimported batch>` are hard-deleted. These records are bounded to this batch's lifecycle by Guardrail A.
- Historical records for this entity with `batch_id != <this batch>` must not exist per Guardrail A. If any are found during execution (a spec-bug case), the purge must abort with a loud error rather than deleting them.
- Edges owned by this same batch that were connected to the swept entity are cascade-hard-deleted along with their `batch_id == <this batch>` history rows.
- Edges owned by other batches would have triggered Guardrail B, so the candidate would have been skipped. If one is found during execution (a spec-bug case), the purge must abort with a loud error.

### Audit Trail

- The `BatchEvent` of type `FORCE_REIMPORT` records `purge: true` and lists the `purged_entities: [entity_id, ...]` ids.
- The entities themselves are gone from the DB after purge, so the BatchEvent is the only remaining record that they existed. This is accepted for the narrow use case and cannot be expanded without re-specifying.
- A batch whose purge has executed is still the same batch entity. The batch row and its event history persist; only its ephemeral content is removed.

### Reporting

The importer's force-reimport report must include:

- `purged_entities`: list of `{entity_id, entity_type}` objects for entities hard-deleted (empty when `--purge` is not set)

### Non-Goals

- `--purge` does not enable deletion of entities created by other batches. Guardrail A still applies.
- `--purge` does not purge batch metadata or other batches' records. Scope is strictly the sweep's output for this invocation.
- `--purge` is not a general-purpose hard-delete tool. Any other hard-delete use case must be proposed as a separate requirement with its own gating.

### Future: Chokepoint With Service-Layer Purge

A sibling requirement, `req-grid-service-purge` (in `tap_grid/specs/spec-grid-service-delete.md`), introduces a general per-entity hard-delete primitive (`purge_node`) for the dev-reset use case. Both surfaces enforce the same DEBUG-only invariant and the same "edges go with the entity, neighbors do not" cascade. They were implemented separately so the GRIFT sweep purge's batch-scoped guardrails (Guardrail A / B) stay in place and the dev-reset CLI could land without re-touching the importer.

A future refactor should route this requirement's per-entity hard-delete sequence through `purge_node`, so there is exactly one place that knows how to remove a typed row + Entity row + touching edges + history rows + BatchEvent rows from the grid. The GRIFT sweep retains its batch-scoped ownership guardrails on top of the shared primitive. Until that refactor lands, the two surfaces are kept in sync by hand; any change to the hard-delete sequence here must also land in `purge_node` and vice versa. Tracked by this Future note and the sibling note on `req-grid-service-purge`.

## Dangling Edge Modes
----
RID: `req-grid-import-grift-dangling`
Status: `Implemented`

The importer should support two dangling-edge modes.

### Strict Mode

- any dangling edge is a preflight failure
- no batch transaction begins

### Permissive Mode

- preflight records each dangling edge
- execution skips only the offending edges
- each skipped edge is logged
- valid nodes and valid edges may still import

In both modes, dangling-edge analysis is completed during preflight, not discovered opportunistically mid-transaction.

## Import-Side Provenance
----
RID: `req-grid-import-grift-provenance`
Status: `Implemented`

GRIFT carries originating identities and batch metadata, but import-side provenance is owned by the importing grid.

### Rules

- the importing grid records its own actor, history, and batch-side effects locally
- serialized batch actor identity is omitted in v0 and must not be required for import
- local patching or upsert behavior is tracked in the importing grid's own history systems
- GRIFT v0 does not replay foreign history or FLIP state

### Batch Description JSON

The importer should record importer metadata in the local batch `description_json` using the existing TAP structured-description wrapper:

```json
{
  "format": "tap.grift.import.v0",
  "data": {
    "importer": "grift",
    "grift_version": "0",
    "import_mode": "upsert",
    "dangling_edge_mode": "permissive",
    "imported_at": "2026-04-06T16:00:00Z",
    "source_batch_entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc001"
  }
}
```

Rules:

- importer metadata uses `format == "tap.grift.import.v0"`
- if the incoming batch already carries `description_json` with a format other than `tap.grift.import.v0`, the importer preserves the caller's `format` string verbatim at the top level and nests importer metadata under the reserved key `data._tap_grift_import` to avoid collision with caller-owned data keys
- if the imported batch metadata already uses `format == "tap.grift.import.v0"`, the importer may overwrite that format block with the new local import metadata rather than nesting ambiguous duplicate copies
- if the incoming batch carries no `description_json`, has an empty one, or has a malformed shape, the importer emits `{"format": "tap.grift.import.v0", "data": <importer metadata>}`
- the reserved key `_tap_grift_import` inside `description_json.data` is owned by the importer; callers must not use it for their own content
- source batch timestamps from the GRIFT payload must be preserved in importer metadata rather than treated as the local batch creation timestamps
- local batch lifecycle timestamps remain local infrastructure timestamps owned by the importing grid
- when present in the GRIFT batch payload or batch envelope, source batch timestamps must be copied into the importer metadata block (either flat at `description_json.data` when the importer owns the whole block, or nested at `description_json.data._tap_grift_import` when preserving a caller format) under source-prefixed keys
- the importer must not assign GRIFT-provided source batch timestamps to the local `Batch.started_at` or `Batch.closed_at` fields

Recommended preserved source timestamp keys:

- `source_started_at`
- `source_closed_at`
- `source_created_at`
- `source_updated_at`

## Import Results
----
RID: `req-grid-import-grift-results`
Status: `Implemented`

The importer should return a structured result describing what happened.

### Result Shape

At minimum the result should include:

- `success`: overall boolean
- `grift_version`: file version string
- `import_mode`: importer mode string
- `dangling_edge_mode`: importer dangling-edge mode string
- `reference_time`: RFC 3339 UTC datetime string
- `counts`: aggregate counts object
- `imported_batches`: array
- `skipped_batches`: array
- `errors`: array
- `warnings`: array

### Issue Object

`errors` and `warnings` share one issue object shape.

Every issue object should include:

- `code`: stable machine-readable code
- `message`: human-readable message
- `phase`: one of `parse`, `schema`, `validation`, `preflight`, `execution`
- `path`: simple JSONPath string
- `entity_id`: UUID string or `null`
- `batch_entity_id`: UUID string or `null`
- `entity_type`: string or `null`
- `operation`: string or `null`

Optional edge context when relevant:

- `from_entity_id`
- `to_entity_id`
- `edge_entity_id`

Rules:

- every non-file-level issue should include an `entity_id` when the affected object can be identified
- every issue must include a `path`
- file-level issues use `path == "$"` and `entity_id == null`
- one issue is emitted per violated field, not one giant grouped object per entity

### Batch Summary Object

Each entry in `imported_batches` should include:

- `batch_entity_id`
- `path`
- `nodes_imported`
- `edges_imported`
- `edges_skipped`
- `errors_count`
- `warnings_count`

Each entry in `skipped_batches` should include:

- `batch_entity_id`
- `path`
- `reason`

### Counts Object

Recommended aggregate counts:

- `batches_imported`
- `batches_skipped`
- `nodes_imported`
- `edges_imported`
- `edges_skipped`
- `errors`
- `warnings`

### Error Code Taxonomy

v0 should define stable codes for common importer outcomes, including:

- `invalid_json`
- `schema_validation_failed`
- `duplicate_entity_id`
- `duplicate_batch_id`
- `unknown_entity_type`
- `payload_validation_failed`
- `timestamp_in_future`
- `timestamp_order_invalid`
- `entity_type_mismatch`
- `dangling_edge`
- `batch_already_imported`
- `execution_failed`

### Result Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:tap:grift-import:v0:result",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "success",
    "grift_version",
    "import_mode",
    "dangling_edge_mode",
    "reference_time",
    "counts",
    "imported_batches",
    "skipped_batches",
    "errors",
    "warnings"
  ],
  "properties": {
    "success": {
      "type": "boolean"
    },
    "grift_version": {
      "type": "string",
      "minLength": 1
    },
    "import_mode": {
      "type": "string",
      "minLength": 1
    },
    "dangling_edge_mode": {
      "type": "string",
      "enum": ["strict", "permissive"]
    },
    "reference_time": {
      "type": "string",
      "format": "date-time"
    },
    "counts": {
      "$ref": "#/$defs/Counts"
    },
    "imported_batches": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/ImportedBatch"
      }
    },
    "skipped_batches": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/SkippedBatch"
      }
    },
    "errors": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/Issue"
      }
    },
    "warnings": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/Issue"
      }
    }
  },
  "$defs": {
    "Counts": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "batches_imported",
        "batches_skipped",
        "nodes_imported",
        "edges_imported",
        "edges_skipped",
        "errors",
        "warnings"
      ],
      "properties": {
        "batches_imported": {"type": "integer", "minimum": 0},
        "batches_skipped": {"type": "integer", "minimum": 0},
        "nodes_imported": {"type": "integer", "minimum": 0},
        "edges_imported": {"type": "integer", "minimum": 0},
        "edges_skipped": {"type": "integer", "minimum": 0},
        "errors": {"type": "integer", "minimum": 0},
        "warnings": {"type": "integer", "minimum": 0}
      }
    },
    "Issue": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "code",
        "message",
        "phase",
        "path",
        "entity_id",
        "batch_entity_id",
        "entity_type",
        "operation"
      ],
      "properties": {
        "code": {
          "type": "string",
          "minLength": 1
        },
        "message": {
          "type": "string",
          "minLength": 1
        },
        "phase": {
          "type": "string",
          "enum": ["parse", "schema", "validation", "preflight", "execution"]
        },
        "path": {
          "type": "string",
          "minLength": 1
        },
        "entity_id": {
          "oneOf": [
            {"type": "null"},
            {"type": "string", "format": "uuid"}
          ]
        },
        "batch_entity_id": {
          "oneOf": [
            {"type": "null"},
            {"type": "string", "format": "uuid"}
          ]
        },
        "entity_type": {
          "oneOf": [
            {"type": "null"},
            {"type": "string", "minLength": 1}
          ]
        },
        "operation": {
          "oneOf": [
            {"type": "null"},
            {"type": "string", "minLength": 1}
          ]
        },
        "from_entity_id": {
          "type": "string",
          "format": "uuid"
        },
        "to_entity_id": {
          "type": "string",
          "format": "uuid"
        },
        "edge_entity_id": {
          "type": "string",
          "format": "uuid"
        }
      }
    },
    "ImportedBatch": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "batch_entity_id",
        "path",
        "nodes_imported",
        "edges_imported",
        "edges_skipped",
        "errors_count",
        "warnings_count"
      ],
      "properties": {
        "batch_entity_id": {"type": "string", "format": "uuid"},
        "path": {"type": "string", "minLength": 1},
        "nodes_imported": {"type": "integer", "minimum": 0},
        "edges_imported": {"type": "integer", "minimum": 0},
        "edges_skipped": {"type": "integer", "minimum": 0},
        "errors_count": {"type": "integer", "minimum": 0},
        "warnings_count": {"type": "integer", "minimum": 0}
      }
    },
    "SkippedBatch": {
      "type": "object",
      "additionalProperties": false,
      "required": ["batch_entity_id", "path", "reason"],
      "properties": {
        "batch_entity_id": {"type": "string", "format": "uuid"},
        "path": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1}
      }
    }
  }
}
```
