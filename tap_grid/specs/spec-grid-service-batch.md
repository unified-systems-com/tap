# Grid Service Batch Specification

## Philosophy

Batching is the write execution model for the TAP service layer. Treating all writes, including single-object writes, as batch-backed operations keeps provenance and execution semantics consistent while allowing dry-run, per-item diagnostics, and transactional all-or-nothing behavior.

Batch records should also be legible as first-class change events. They need enough human-readable and machine-readable metadata to explain what a batch represents, why it happened, and how it can be related back to upstream systems such as source control, scanners, import jobs, and other structured change producers.

## Goals

|    |                  |                                                                                 |
| :---: | ---           | ---                                                                             |
| 1. | Unified           | All writes participate in the same batch semantics                              |
| 2. | Transactional     | Multi-operation writes can be validated and committed consistently              |
| 3. | Inspectable       | Dry-run and per-item diagnostics support humans and bots before commit          |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-service-batch-model | [Batch Model](#batch-model) | Implemented | Batch as a first-class Entity with lifecycle states and service functions |
| req-grid-service-batch-event | [Batch Event Log](#batch-event-log) | Implemented | Append-only per-operation audit log linked to each Batch |
| req-grid-service-batch-all | [All Writes Are Batch-Backed](#all-writes-are-batch-backed) | Implemented | Single and multi-object writes share batch semantics |
| req-grid-service-batch-metadata | [Batch Metadata Fields](#batch-metadata-fields) | Implemented | Human-readable and machine-readable batch metadata |
| req-grid-service-batch-infra | [Batch ID As Infrastructure](#batch-id-as-infrastructure) | Implemented | CallerContext introduced; batch_id threading via ContextVar implemented |
| req-grid-service-batch-signals | [Signal Elimination](#signal-elimination) | Implemented | tap_flip/batch/signals.py deleted; provenance in BaseModel.save() |
| req-grid-service-batch-dryrun | [Dry-Run Behavior](#dry-run-behavior) | Implemented | Full validation without persistence |
| req-grid-service-batch-diag | [Per-Item Diagnostics](#per-item-diagnostics) | Implemented | Batch partial diagnostics and reporting |
| req-grid-service-batch-tx | [Transactional Commit Behavior](#transactional-commit-behavior) | Implemented | All-or-nothing commit model |
| req-grid-service-batch-precommit-consistency | [Pre-Commit Consistency Phase](#pre-commit-consistency-phase) | Implemented | After per-op success, before commit, run cross-row graph-consistency checks (hotlinks today) and attribute failures per-op |
| req-grid-service-batch-occ | [Optimistic Concurrency Per Operation](#optimistic-concurrency-per-operation) | Approved for Development | `WriteOperation.entity_expected_version` declares the local `Entity.version` an op expects; the verb performs an atomic check-and-mutate and surfaces `entity_version_conflict` |


### Batch Model
----
RID: `req-grid-service-batch-model`

Status: `Implemented`

A Batch is a first-class TAP Entity representing a logical group of writes. It carries lifecycle state and metadata describing what the batch represents, why it happened, and how it relates to upstream systems.

#### Status Details
`Batch` extends `BaseModel` (ENTITY_TYPE `"batch"`), giving it a backing Entity on the spine. Batches can be queried, linked, and traversed like any other entity. Batch is intended to be an internal-only model type managed by dedicated batch services rather than ordinary generic CRUD. History is inherited from BaseModel.

#### Fields

| Field | Type | Nullable | Default | Description |
| --- | --- | --- | --- | --- |
| `entity` | OneToOne → Entity | No | — | Backing Entity on the TAP spine. `entity.entity_type = "batch"`. |
| `name` | CharField(255) | No | `""` | Human-readable batch name; mirrors the backing Entity name. |
| `description` | TextField | No | `""` | Long-form free-text description of the batch purpose. |
| `description_json` | JSONField | Yes | `null` | Structured metadata; must conform to `{format, data}` shape when present. See `req-grid-service-batch-metadata`. |
| `status` | CharField choices | No | `"open"` | Lifecycle state. One of `open`, `closed`, `failed`. |
| `source` | CharField(255) | No | `""` | Source identifier, e.g. `"scanner:aws"`, `"import:csv"`, `"api:v1"`. |
| `metadata` | JSONField | No | `{}` | Free-form metadata: parameters, counts, correlation keys, etc. |
| `actor` | FK → User | Yes | `null` | User who initiated the batch. `SET_NULL` on user deletion. |
| `started_at` | DateTimeField | No | auto | When the batch was opened. Set once on creation. |
| `closed_at` | DateTimeField | Yes | `null` | When the batch was closed or failed. Null while open. |
| `error_message` | TextField | No | `""` | Error details populated when status is `"failed"`. |

#### Lifecycle

```
open ──► closed   (via close_batch())
open ──► failed   (via fail_batch())
```

Transitioning from any non-open state is an error. Closed and failed are terminal states; there is no re-open transition in v1.

#### Service Functions

| Function | Description |
| --- | --- |
| `create_batch(source, actor, name, description, description_json, metadata)` | Create a new open Batch and its backing Entity. `name` is used for both the Batch and its backing Entity. |
| `close_batch(batch)` | Transition `open → closed`; sets `closed_at`. Raises `ValueError` if not open. |
| `fail_batch(batch, error_message)` | Transition `open → failed`; sets `closed_at` and `error_message`. Raises `ValueError` if not open. |
| `get_batch(batch_id)` | Retrieve a Batch by its Entity UUID. Returns `None` if not found. |
| `get_batch_events(batch_id)` | Return all `BatchEvent` records for a Batch. |
| `get_entity_batches(entity_id)` | Return all Batches that have events touching a given Entity. |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-model-1 | Batch Is An Entity | Implemented | Batch extends BaseModel and has a backing Entity on the TAP spine. | ENTITY_TYPE = `"batch"` |
| req-grid-service-batch-model-2 | Lifecycle States | Implemented | Batch supports `open`, `closed`, and `failed` states. | `BatchStatus` TextChoices |
| req-grid-service-batch-model-3 | Open Is Default | Implemented | New batches begin in `open` state. | |
| req-grid-service-batch-model-4 | Closed At Set On Transition | Implemented | `closed_at` is set when status transitions to `closed` or `failed`. | |
| req-grid-service-batch-model-5 | Invalid Transition Rejected | Implemented | Attempting to close or fail a non-open batch raises an error. | `ValueError` |
| req-grid-service-batch-model-6 | Actor Captured | Implemented | Batch records the initiating user as `actor`; survives user deletion as `null`. | |
| req-grid-service-batch-model-7 | Infrastructure Exempt From Recursive Batching | Implemented | Batch creation is handled as service infrastructure rather than an ordinary user-managed write path, preventing recursive provenance loops. | `Batch.INTERNAL_ONLY = True`; FLIP skipped; see `req-grid-service-batch-all-3` and `req-grid-entity-internal` |

#### Future
Define whether batches should support named kinds (import, user-edit, sync, admin) as a `source` convention or a structured field. Define re-open semantics if operational needs require them.


### Batch Event Log
----
RID: `req-grid-service-batch-event`

Status: `Implemented`

Each Batch accumulates an append-only log of per-operation events. Events record what happened to which Entity within the batch, enabling correlation, replay, and audit without requiring full delta reconstruction.

#### Status Details
`BatchEvent` is a standalone model (not a BaseModel subclass) — it is internal bookkeeping and does not need its own Entity on the spine. Events are immutable after creation. Delta reconstruction is handled by `django-simple-history` on the affected models; `BatchEvent` provides correlation, not content.

#### Fields

| Field | Type | Nullable | Default | Description |
| --- | --- | --- | --- | --- |
| `id` | UUIDField (PK) | No | uuid7 | Unique event identifier. |
| `batch` | FK → Batch | No | — | The Batch this event belongs to. `CASCADE` on batch deletion. |
| `event_type` | CharField choices | No | — | One of `create`, `update`, `delete`, `link`, `unlink`. |
| `entity_id` | UUIDField | No | — | The affected Entity's UUID. |
| `entity_type` | CharField | No | — | Type slug of the affected Entity (denormalised for fast filtering). |
| `model_name` | CharField | No | `""` | ORM model class name, e.g. `"Character"`. Empty for raw entity ops. |
| `timestamp` | DateTimeField | No | auto | When the event was recorded. |
| `actor` | FK → User | Yes | `null` | User responsible for this specific operation. `SET_NULL` on user deletion. |
| `metadata` | JSONField | No | `{}` | Free-form per-event metadata (e.g. field names changed, count deltas). |

#### Event Types

| Value | Meaning |
| --- | --- |
| `create` | A new node or edge was created. |
| `update` | An existing node or edge was mutated (patch or replace). |
| `delete` | A node or edge was deleted (tombstoned). |
| `link` | An edge was created between two existing nodes. |
| `unlink` | An edge was removed. |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-event-1 | Events Are Append-Only | Implemented | BatchEvent records are created once and never modified. | No update or delete permissions in admin |
| req-grid-service-batch-event-2 | Event Links To Batch | Implemented | Every BatchEvent belongs to exactly one Batch. | FK with CASCADE |
| req-grid-service-batch-event-3 | Entity Identity Captured | Implemented | Each event records the affected Entity's UUID and type. | Enables cross-batch entity audit |
| req-grid-service-batch-event-4 | All Five Event Types Supported | Implemented | `create`, `update`, `delete`, `link`, `unlink` are all valid event types. | |
| req-grid-service-batch-event-5 | Actor Captured Per Event | Implemented | Each event records the acting user; survives user deletion as `null`. | |
| req-grid-service-batch-event-6 | Events Cascade On Batch Delete | Implemented | Deleting a Batch removes its events. | `on_delete=CASCADE` |

#### Future
Define whether event log retention should be configurable separately from Batch retention. Define whether events should carry a delta hash or reference to the history record for deeper traceability.


### All Writes Are Batch-Backed
----
RID: `req-grid-service-batch-all`

Status: `Implemented`

Every service-layer write participates in batch semantics, including single-object writes.

#### Status Details
This requirement captures the decision to use one consistent batch model rather than a split system for “simple writes” versus “real batches.”

#### Implementation
Single-object writes are represented as one-operation batches. Multi-object write flows are represented as multi-operation batches. If TAP later needs to distinguish batch kinds, that can be modeled as a batch property rather than a separate write system.

**Exemption:** Batch ID creation itself is an infrastructure-level operation and is explicitly exempt from this requirement. The service layer creates a batch_id before executing writes; that creation does not recursively require its own batch context. See `req-grid-service-batch-infra`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-all-1 | Single Writes Use Batch Semantics | Implemented | Single-object writes are treated as batch-backed operations. | |
| req-grid-service-batch-all-2 | Multi Writes Use Same Batch Model | Implemented | Multi-object writes use the same batch abstraction rather than a separate execution system. | |
| req-grid-service-batch-all-3 | Batch Creation Is Exempt | Implemented | The infrastructure operation of creating a batch_id is explicitly exempt from the batch-backed requirement. | |

#### Future
Add batch-type metadata if later operational needs require distinguishing import, user edit, sync, or admin-driven batch categories.


### Batch Metadata Fields
----
RID: `req-grid-service-batch-metadata`

Status: `Implemented`

Batch records should carry a small, explicit metadata surface that supports both human understanding and machine-usable correlation.

#### Status Details
This requirement introduces richer batch metadata beyond batch identity alone. It is intended to make batches useful as contextual change records for humans, bots, and future search/reporting surfaces.

#### Implementation
A batch should support these metadata fields:

- `name`: required human-readable batch name (also used as the backing Entity name)
- `description`: optional longer free-form human-readable description
- `description_json`: optional structured metadata object supplied by the batch creator

`name` should be stored as a standard short text field such as a `CharField`.

`description` should be stored as a free-form text field.

`description_json` should be constrained to this fixed top-level shape:

```json
{
  "format": "git",
  "data": {
    "commit": "abc123"
  }
}
```

Rules for `description_json`:

- top-level value must be an object
- top-level keys are fixed to `format` and `data`
- `format` is a required non-empty string describing the payload format
- `data` is a required object
- `additionalProperties` is false at the top level
- callers may add arbitrary format-specific fields inside `data`

`description_json` is caller-supplied metadata. TAP does not impose a canonical domain schema beyond the fixed top-level wrapper and object-only requirements.

This structure gives TAP a stable discriminator for parsing, rendering, search, and downstream automation without forcing all callers into one shared domain-specific schema.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-metadata-1 | Name Required | Implemented | Each batch stores a required human-readable `name`; also used as the backing Entity name. | Intended for humans and AI context. |
| req-grid-service-batch-metadata-2 | Description Optional | Implemented | Each batch may store an optional longer-form `description`. | |
| req-grid-service-batch-metadata-3 | Description JSON Optional | Implemented | Each batch may store optional structured `description_json` metadata. | |
| req-grid-service-batch-metadata-4 | Fixed Top-Level JSON Shape | Implemented | `description_json`, when present, must be an object with exactly `format` and `data` keys. | No additional top-level keys. |
| req-grid-service-batch-metadata-5 | Data Object Only | Implemented | `description_json.data` must itself be an object. | |
| req-grid-service-batch-metadata-6 | Format String Required | Implemented | `description_json.format` must be a non-empty string describing the metadata format. | |

#### Future
Define whether TAP should publish a registry of known batch metadata formats and whether specific formats should get richer search/rendering helpers.


### Batch ID As Infrastructure
----
RID: `req-grid-service-batch-infra`

Status: `Implemented`

The service layer is responsible for generating a batch_id at the start of every write operation and threading it downstream to models. Models consume the batch_id; they do not create it.

#### Status Details
This requirement formalises the boundary between the service layer's orchestration responsibility and the model's provenance responsibility. It replaces the previous approach where batch context was managed via a thread-local context manager in `tap_flip`.

#### Implementation
At the start of every write pipeline execution the service layer:

1. Checks CallerContext for an existing batch_id (for callers that have pre-established a batch scope).
2. If none is present, generates a new UUIDv7 as the batch_id for this operation.
3. Places the batch_id in the CallerContext that flows through the rest of the pipeline.

Models receive batch_id through CallerContext and use it to update `flip_map` and any other provenance fields during `save()`. Models do not call out to a batch service to register or track the batch; they only record the identifier they were given.

Batch_id creation does not require persisting a Batch entity before writes can proceed. Any Batch audit entity is an optional append-only artifact that may be written after the primary write completes, not a prerequisite for it.

The previous `batch_context()` context manager in `tap_flip.batch.service` is superseded by this mechanism and should be removed during the FLIP simplification pass.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-infra-1 | Service Layer Generates Batch ID | Implemented | The service layer generates a batch_id at the start of each write pipeline execution if none is present in CallerContext. | |
| req-grid-service-batch-infra-2 | Batch ID Flows Via Context | Implemented | batch_id reaches models through CallerContext rather than a thread-local or separate context manager. | |
| req-grid-service-batch-infra-3 | Models Consume Not Create | Implemented | Models use the batch_id provided to them; they do not initiate batch creation. | |
| req-grid-service-batch-infra-4 | No Batch Entity Prerequisite | Implemented | A Batch audit entity is not required to exist before writes can proceed; it is an optional post-write artifact. | |

#### Future
Define whether Batch audit entities are written synchronously after each pipeline execution or asynchronously, and what their retention policy is.


### Signal Elimination
----
RID: `req-grid-service-batch-signals`

Status: `Implemented`

Signal-based batch event recording is eliminated. Provenance is recorded directly in `BaseModel.save()` using the batch_id from CallerContext.

#### Status Details
The previous implementation used Django signals (`tap_flip.batch.signals`) to intercept model saves and record `BatchEvent` records. This approach is being replaced because:

- Signals fire outside the service layer pipeline, making them invisible to dry-run, authz, and other pipeline stages.
- Signal ordering is fragile and difficult to test in isolation.
- The service layer's batch_id threading model makes signals unnecessary.

#### Implementation
`BaseModel.save()` consumes the batch_id from the active CallerContext directly and updates `flip_map`. No signal handlers are needed for this path.

The existing signal registration in `tap_flip.batch.signals` should be removed during the FLIP simplification pass. Any `BatchEvent` append behavior that needs to survive should be moved into a method called explicitly within `BaseModel.save()` or the service layer pipeline step 10 (provenance recording).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-signals-1 | No Signal-Based Batch Recording | Implemented | Batch provenance recording does not rely on Django post-save signals. | |
| req-grid-service-batch-signals-2 | Provenance In Save | Implemented | `BaseModel.save()` handles flip_map updates using batch_id from CallerContext. | |
| req-grid-service-batch-signals-3 | Legacy Signals Removed | Implemented | `tap_flip.batch.signals` signal handlers are removed during the FLIP simplification pass. | |

#### Future
Evaluate whether any observability events (not provenance) benefit from a lightweight signal or hook after the primary write pipeline stabilises.


### Dry-Run Behavior
----
RID: `req-grid-service-batch-dryrun`

Status: `Implemented`

The batch system should support dry-run execution for both single-object and multi-object writes.

#### Status Details
This requirement reflects the preferred development and operational workflow for safe validation-first execution.

#### Implementation
Dry-run mode:

- runs the full validation stack
- produces per-item diagnostics
- does not persist changes
- does not commit the transaction

Dry-run is a request-time flag, not a separate API family.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-dryrun-1 | Dry Run Available For All Writes | Implemented | Dry-run mode is available for single-object and multi-object write execution. | |
| req-grid-service-batch-dryrun-2 | Full Validation In Dry Run | Implemented | Dry-run mode executes the same validation stack as a real write. | |
| req-grid-service-batch-dryrun-3 | No Persistence In Dry Run | Implemented | Dry-run mode performs no durable writes. | |

#### Future
Clarify whether dry-run should record ephemeral observability events once the instrumentation story is designed.


### Per-Item Diagnostics
----
RID: `req-grid-service-batch-diag`

Status: `Implemented`

Batch execution should return structured per-item diagnostics so callers can understand which requested operations would fail and why.

#### Status Details
This requirement defines “batch partial diagnostics” even when commit behavior remains all-or-nothing.

#### Implementation
Per-item diagnostics should support, at minimum:

- requested operation
- target object/type
- status
- stable error code when failed
- safe human-readable message
- machine-usable detail payload
- correlation/debug reference where applicable

These diagnostics are especially important for dry-run flows but also useful for failed committed batches.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-diag-1 | Operation Identified Per Item | Implemented | Batch diagnostics identify the requested operation for each item. | `WriteResult.operation` |
| req-grid-service-batch-diag-2 | Safe Message And Stable Code | Implemented | Failed item diagnostics include a safe message and stable error code. | |
| req-grid-service-batch-diag-3 | Machine Detail Payload | Implemented | Diagnostics include structured machine-usable detail payloads for automation and tooling. | |

#### Future
Define how verbose result mode enriches per-item diagnostics with deeper references for admin and bot workflows.


### Transactional Commit Behavior
----
RID: `req-grid-service-batch-tx`

Status: `Implemented`

Committed batch writes should use all-or-nothing transaction semantics.

#### Status Details
This requirement captures the current intended commit model.

#### Implementation
If a committed batch fails validation or persistence for any operation, the batch does not partially commit graph changes. Dry-run diagnostics may still report which operations would have failed, but real commit behavior remains transactional.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-tx-1 | All Or Nothing Commit | Implemented | A committed batch either fully succeeds or fully rolls back. | |
| req-grid-service-batch-tx-2 | Diagnostics Survive Failure | Implemented | Failed committed batches still return structured diagnostics explaining the failure set. | |

#### Future
Revisit partial commit models only if a concrete operational need emerges; they are not part of the v1 batch contract.

### Pre-Commit Consistency Phase
----
RID: `req-grid-service-batch-precommit-consistency`

Status: `Implemented`

A batch is the smallest unit in which cross-row graph-consistency invariants can be evaluated. Per-row validation in `_execute_write_pipeline` is the right place to check that *a row's payload* is well-formed, but it is the wrong place to check invariants about *the post-batch graph* — those invariants need every node and edge in the batch to have already landed. The batch pipeline therefore exposes a dedicated phase that runs after every per-op pipeline has succeeded and before the atomic transaction commits.

In v0 the sole consumer is hotlink validation (`req-grid-hotlink-deferred` in `spec-grid-hotlink.md`). The phase is specified here to formalize *when* such checks run inside `write_batch`, so future graph-consistency checks have a documented seam to attach to rather than reinventing the timing one consumer at a time.

#### Status Details
Implemented in `tap_grid/services.py` `write_batch`. Hotlink deferral activates the phase by enqueuing checks via the side-channel ContextVar defined in `tap_grid/caller_context.py`. After the per-op loop completes successfully, `write_batch` drains the queue, attributes any failures to the matching per-op `WriteResult`, and raises `_BailOut` on any failure so the surrounding `transaction.atomic()` rolls back. Dry-run rollback semantics are preserved.

#### Implementation

**Phase position.** The consistency phase runs inside the same `transaction.atomic()` block as the per-op loop, after the loop completes with every `WriteResult.success == True`, and before the dry-run rollback / commit boundary. If any per-op pipeline failed earlier, the batch has already short-circuited via `_BailOut`; the consistency phase is skipped because the atomic block is already rolling back.

**Drain behavior.** Each consumer of the phase (today: hotlinks) deposits work into a context-bound queue during the per-op loop and drains its own queue inside the consistency phase. The phase itself does not define a generic registry in v0; it documents the seam and the drain timing. Adding a second consumer is a future refactor, not a v0 surface (`Future`, below).

**Failure attribution.** Per-row validation failures attribute to one `WriteResult` naturally because the failure happens inside that op's pipeline. Consistency-phase failures are *about* one or more entities — typically one — and must be attributed back to the `WriteResult` of the operation whose `entity_id` the consistency check is reporting on. The phase does this by entity_id lookup against the `results` list: each matching result is flipped to `success=False` and the consistency error is appended.

**Collect-all semantics.** A consistency phase collects every failure across its inputs before raising, matching the all-fields behavior already established in per-row validation (`BaseModel.full_validate` collects every field error before raising). Each consumer enumerates its full deferred set rather than stopping at the first failure, so a single drain pass surfaces the complete picture of what the batch left inconsistent.

**Rollback consequence.** Any consistency-phase failure raises `_BailOut`, rolling back the entire atomic block. The batch is all-or-nothing whether the failure originated in per-row validation or in the consistency phase.

**Error code separation.** Consistency-phase failures should use codes distinct from per-row `validation_error`, so downstream consumers (e.g. the GRIFT importer's `execution_failed` mapping) can distinguish payload bugs from cross-row consistency bugs. Hotlinks use `hotlink_validation_failed`; future consumers should follow the same convention.

#### Development
The seam exists because cross-row invariants are real and recurring: hotlinks today, plausibly future constraint checks that depend on a node + its neighbors landing together, plausibly future referential-integrity assertions across edges that the batch creates simultaneously. Each one breaks if validated per-row. Codifying the phase once means future consumers attach to a known boundary instead of inventing one inside their own subsystem.

The phase deliberately runs *before* commit, not after. A post-commit check could only report failures after data persisted, which would invert the batch contract from "all-or-nothing" to "best-effort with eventual diagnostics" — wrong for v0's transactional model. The cost is the consistency phase reads from the in-transaction snapshot, which is exactly what every consumer wants (it sees the batch's intended end-state graph).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-precommit-consistency-1 | Phase Runs Inside Atomic Block | Implemented | The consistency phase runs inside the same `transaction.atomic()` as the per-op loop, so any failure rolls back every batch write. | |
| req-grid-service-batch-precommit-consistency-2 | Phase Runs After Per-Op Success | Implemented | The phase runs only after every per-op `WriteResult.success == True`. A prior per-op failure short-circuits the batch via `_BailOut` and the phase is skipped. | The atomic block rolls back regardless. |
| req-grid-service-batch-precommit-consistency-3 | Phase Runs Before Commit / Dry-Run Rollback | Implemented | The phase runs before the dry-run rollback branch and before the implicit commit at the end of the atomic block. | Dry-run semantics preserved. |
| req-grid-service-batch-precommit-consistency-4 | Per-Op Failure Attribution | Implemented | Consistency failures are attributed to the `WriteResult` whose `entity_id` matches the failure's subject; that result is flipped to `success=False` with the failure appended. | If multiple operations touched the same entity, attribution falls on the last such operation. |
| req-grid-service-batch-precommit-consistency-5 | Collect All Failures | Implemented | The phase collects every failure before raising, matching the all-fields behavior of per-row validation. No first-failure bail. | Mirrors `BaseModel.full_validate` collection semantics. |
| req-grid-service-batch-precommit-consistency-6 | All-Or-Nothing Rollback | Implemented | Any consistency-phase failure rolls back the entire batch via `_BailOut`. | Same code path as per-op failures. |
| req-grid-service-batch-precommit-consistency-7 | Distinct Error Codes | Implemented | Consistency-phase failures use codes distinct from per-row `validation_error` so callers can distinguish payload errors from cross-row consistency errors. | Hotlinks use `hotlink_validation_failed`. |

#### Future
v0 has exactly one consumer (hotlink validation, `req-grid-hotlink-deferred`). If a second consumer lands, extract a small registry that lets consumers register `drain_callback(results)` against the phase rather than each subsystem hard-coding its own ContextVar plumbing. Do not pre-build the registry; let demand pull it.

The phase is also the natural attachment point for future read-side consistency assertions (e.g. "every edge created by this batch resolves to a node that is either pre-existing or created earlier in this same batch"). Such checks are out of scope for v0 but should land here when they land.


### Optimistic Concurrency Per Operation
----
RID: `req-grid-service-batch-occ`

Status: `Approved for Development`

Service-layer write and delete verbs expose an `entity_expected_version` parameter so callers can engage optimistic concurrency control at per-operation granularity. The verb enforces the version check via a single conditional Entity-row guard inside the verb's transaction (see Atomic Entity-Row Guard below for the two equivalent shapes the guard may take), guaranteeing a zero-width race window between the check and the act and recording exactly one `Entity.version` increment per successful call.

This requirement is the service-layer half of GRIFT's optimistic-concurrency contract (`req-grift-concurrency-version` in `spec-grift-v0.md`, enforced by `req-grid-import-grift-occ` in `spec-grid-import-grift.md`) and is also available to non-GRIFT callers. Direct service-layer callers (admin tools, future API surfaces, internal scripts) can opt into OCC without going through GRIFT.

#### Status Details

Approved for Development. Implementation extends `WriteOperation` with an optional `entity_expected_version` field, threads it through `_execute_write_pipeline` to the underlying verb, and surfaces conflicts as `WriteResult.errors[].code == "entity_version_conflict"`. The per-verb specifications (`spec-grid-service-write.md`, `spec-grid-service-delete.md`) define the parameter signature on each public verb.

#### Implementation

**`WriteOperation` carries `entity_expected_version`.** A new optional field, type `int | None`, default `None`. When `None`, the verb runs without a version check (existing behavior). When set, the verb enforces the check via a single conditional Entity-row guard inside the verb's transaction (see Atomic Entity-Row Guard below for the two equivalent shapes the guard may take).

**Atomic Entity-row guard.** The verb enforces the version check via a single conditional guard on the `Entity` row inside the verb's own `transaction.atomic()`. The guard takes one of two equivalent shapes:

1. **Conditional Entity-row update.** A statement of the form `UPDATE entity SET version = version + 1, updated_at = now() WHERE id = X AND version = N RETURNING ...` runs as the first SQL action of the verb. If zero rows match, no other state in this verb's pipeline has changed; the verb raises (see Result Shape below) and the surrounding `transaction.atomic()` rolls back. If one row matches, `Entity.version` has incremented exactly once and the verb proceeds to the typed-model save, history, FLIP propagation, spine name sync, and any other downstream steps inside the same transaction.
2. **`SELECT … FOR UPDATE` on the Entity row.** The verb takes a row-level lock on `Entity` at the start of its pipeline, reads the current version, compares to `entity_expected_version`, raises on mismatch, then proceeds with the same downstream steps and a single explicit `Entity.version += 1` on success.

Both forms satisfy the contract because they share three properties:

- the version comparison and the version increment are part of the same transaction-scoped guard
- exactly one `Entity.version` increment is recorded per successful verb call
- on any failure downstream (typed-model validation, history failure, FLIP failure, hotlink check, deferred hook), the surrounding `transaction.atomic()` rolls back and the increment is undone

The choice between forms is an implementation detail of each verb. Patch/replace verbs that need typed-model `save()` machinery (which currently bumps `version` itself) typically lock the row first and skip a duplicate increment; verbs whose work is fully expressible as a single SQL update (most edge deletes, some purges) typically use the conditional UPDATE form. The contract above is what callers can rely on; the SQL shape is not.

**No double version-bump.** Whichever form a verb uses, the typed-model `save()` path must contribute exactly one effective `Entity.version` increment per successful verb call. If `BaseModel.save()` would otherwise increment `version` on its own, the OCC guard arranges to set or skip that increment so the net change is +1. Verbs are responsible for documenting their integration with `BaseModel.save()` and `HistoricalRecords` so reviewers can confirm the single-increment invariant.

**Verb signatures.** Every write verb accepts `entity_expected_version: int | None = None`:

- `create_node` — `entity_expected_version` is meaningless (no prior version); the parameter is rejected with a stable error if set
- `patch_node`, `replace_node` — `entity_expected_version` enforced as described
- `delete_node` — `entity_expected_version` enforced
- `create_edge` — same rejection-if-set rule as `create_node`
- `patch_edge`, `replace_edge` — `entity_expected_version` enforced
- `delete_edge_by_entity` / `delete_edge` — `entity_expected_version` enforced
- `purge_node`, `purge_edge` — `entity_expected_version` enforced (see `spec-grid-service-delete.md`)

**Result shape.** Two distinct failure cases must be distinguishable in the result:

| Caller state | Local Entity state | Result code | `detail.actual_entity_version` |
| --- | --- | --- | --- |
| `entity_expected_version` omitted | entity missing | `not_found` | absent |
| `entity_expected_version` omitted | entity exists | (success or other error per verb contract) | — |
| `entity_expected_version = N` | entity missing entirely | `entity_version_conflict` | `null` |
| `entity_expected_version = N` | entity exists, `Entity.version = N` | success | — |
| `entity_expected_version = N` | entity exists, `Entity.version ≠ N` | `entity_version_conflict` | `<actual int>` |

Rationale for the split: a direct caller who did not engage OCC and hit a missing entity meant "operate on this entity" and the absence is the relevant failure (`not_found`). A direct caller who declared `entity_expected_version` was asserting "this entity exists with version N" — the absence falsifies that assertion in the same way a wrong-version row does, and the caller's retry-or-surface logic wants to treat both as conflicts. GRIFT removal targets layer their own `on_missing` policy on top of this; see `req-grid-import-grift-occ`.

A `entity_version_conflict` failure becomes a `WriteResult` with:

- `success = False`
- `errors[0].code = "entity_version_conflict"`
- `errors[0].message` — human-readable message including expected vs actual (or "expected vs missing")
- `errors[0].detail` — `{ "entity_expected_version": <int>, "actual_entity_version": <int | null>, "entity_id": <uuid str> }`

A `not_found` failure (direct caller, no OCC, missing entity) uses the existing `ServiceNotFoundError` / `not_found` code with no `actual_entity_version` field — this path is unchanged from pre-OCC behavior.

The new `entity_version_conflict` code is added to the `ServiceError.code` Literal so type-checkers see it.

**Batch interaction.** A `entity_version_conflict` on any operation triggers the standard `_BailOut` path: the surrounding `transaction.atomic()` rolls back; subsequent operations in the batch are not executed. This matches the all-or-nothing commit contract (`req-grid-service-batch-tx`).

**Dry-run.** Dry-run mode performs the version check normally and reports a conflict as it would in real commit mode. The rollback at the end of the dry-run does not change the conflict semantics: callers see the conflict in `WriteResult.errors` even though no data was persisted.

#### Caller Guidance

OCC is opt-in. Callers that engage it own the retry-or-surface decision on conflict. The recommended pattern is the same one documented in `req-grid-import-grift-occ` Client Guidance: re-read state, re-evaluate intent, resubmit or surface to the operator.

The service layer does NOT retry automatically. A future helper module may wrap retry-with-backoff for common patterns (mirror of `client-go`'s `RetryOnConflict`), but that is out of scope for this requirement.

#### Non-Goals

- Caller-managed broad locking is out of scope. A verb may use a verb-internal `SELECT … FOR UPDATE` on its own target Entity row as the implementation of the OCC guard (see Atomic Entity-Row Guard above), but this requirement does not introduce a public surface for callers to declare or hold broader pessimistic locks across multiple operations. Tactical `SELECT FOR UPDATE` inside caller-owned transactions remains available but is not a public verb-contract feature.
- "Latest version wins" or "force overwrite" modes are out of scope. The verbs perform exactly the check the caller declared and never bypass it; bypassing OCC is simply "omit `entity_expected_version`," which is the default behavior.
- Range checks (e.g. `entity_expected_version_at_least`) are out of scope; deferred to a future seam if a use case lands.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-batch-occ-1 | Optional Field On WriteOperation | Approved for Development | `WriteOperation.entity_expected_version: int \| None = None` is added; omitted means no check. | |
| req-grid-service-batch-occ-2 | Atomic Entity-Row Guard | Approved for Development | The version check is enforced via a single conditional guard on the `Entity` row (atomic `UPDATE … WHERE version = N` or `SELECT … FOR UPDATE` + compare) inside the verb's own transaction. Exactly one `Entity.version` increment is recorded per successful verb call; downstream typed-model save / history / FLIP / spine sync run inside the same guarded transaction and contribute no additional version bumps. | Race window is zero; integration with `BaseModel.save()` documented per verb. |
| req-grid-service-batch-occ-3 | Conflict Vs Not-Found Distinguished | Approved for Development | A direct caller with no OCC and a missing entity sees `not_found`. A direct caller with OCC and a missing entity sees `entity_version_conflict` with `actual_entity_version = null`. A direct caller with OCC and a wrong-version entity sees `entity_version_conflict` with `actual_entity_version = <int>`. Detail payload `{entity_expected_version, actual_entity_version, entity_id}`. | GRIFT removal `on_missing` policy applies on top of this in `req-grid-import-grift-occ`. |
| req-grid-service-batch-occ-4 | Create Verbs Reject Expected Version | Approved for Development | `create_node` and `create_edge` reject `entity_expected_version` if set (no prior version exists to expect). | Stable error code, distinct from `entity_version_conflict`. |
| req-grid-service-batch-occ-5 | Conflict Triggers Batch Rollback | Approved for Development | A `entity_version_conflict` triggers the existing `_BailOut` path; the `transaction.atomic()` block rolls back. | All-or-nothing per `req-grid-service-batch-tx`. |
| req-grid-service-batch-occ-6 | Dry-Run Honors The Check | Approved for Development | Dry-run mode performs the check and reports conflicts; the surrounding rollback does not mask the conflict in results. | |
| req-grid-service-batch-occ-7 | No Implicit Retry | Approved for Development | The service layer does not retry on conflict. Callers own retry logic. | |

#### Future

- A future client-side helper module wraps retry-with-backoff for callers that want the K8s `RetryOnConflict` ergonomics; not in v0 scope.
- A future `entity_expected_version_at_least` predicate could support forward-only writers; deferred until demand lands.


**Note — caller-managed rollback (2026-04-10):** Plugin validation (`validate_plugin --level runs`) needs to exercise the full write pipeline and then discard all side effects, including auto-created Batch entities. This is handled today by the validation system wrapping its checks in a caller-owned `transaction.atomic()` block that always rolls back. The batch system itself does not offer a built-in "disposable" or "rollback" mode because the decision to discard results is a caller-level concern, not a batch-level one. `_ensure_batch` was moved inside the service layer's `transaction.atomic()` so that it participates in rollback rather than leaking orphan Batch rows. If a second caller emerges with the same execute-then-discard need, consider extracting a shared `rollback_transaction()` context manager as a utility — but do not add rollback semantics to the batch model itself.


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
