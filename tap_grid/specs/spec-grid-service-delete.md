# Grid Service Delete Specification

## Philosophy

Delete behavior is a critical part of the service-layer contract because it determines how TAP preserves graph integrity when objects are removed. The initial delete contract should be conservative, explicit, and focused on the baseline guarantees already understood, while leaving richer cascade policy design for a dedicated future pass.

## Goals

|    |                  |                                                                                 |
| :---: | ---           | ---                                                                             |
| 1. | Safe              | Deletions preserve core graph integrity                                         |
| 2. | Explicit          | Delete behavior is defined through the service layer rather than implied         |
| 3. | Extensible        | Future richer delete policies can layer on top of a clear baseline contract      |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-service-delete-baseline | [Baseline Delete Semantics](#baseline-delete-semantics) | Implemented | Node/edge delete with entity cascade |
| req-grid-service-delete-scope | [Delete Scope And Wrappers](#delete-scope-and-wrappers) | Implemented | delete_node + delete_edge_by_entity route through write pipeline |
| req-grid-service-delete-tombstone | [Tombstoned Delete Semantics](#tombstoned-delete-semantics) | Implemented | Delete behavior uses `deleted_at` tombstones through the service layer |
| req-grid-service-purge | [Service-Layer Purge](#service-layer-purge) | Implemented | DEBUG-only hard-delete escape hatch; `purge_node` + `manage.py purge_entities` |
| req-grid-service-purge-edge | [Service-Layer Edge Purge](#service-layer-edge-purge) | Implemented | DEBUG-only `purge_edge` primitive for hard-deleting a single Edge entity without node cascade |
| req-grid-service-delete-occ | [Optimistic Concurrency Parameter On Delete And Purge](#optimistic-concurrency-parameter-on-delete-and-purge) | Implemented | Delete and purge verbs accept `entity_expected_version` for atomic check-and-mutate |
| req-grid-service-delete-reason | [Reason And Metadata On Delete](#reason-and-metadata-on-delete) | Partial | `delete_node` carries a typed reason and structured metadata into the batch event and the history reason |
| req-grid-service-delete-cascade | [Contained-Subtree Cascade](#contained-subtree-cascade) | Partial | `cascade="contained"` walks the model's `CONTAINMENT_EDGES` recursively in one transaction, capped and cycle-safe; a refusal on any child rolls it back. Preflight, `cascade_force` and integrity findings are Backlog (down-scoped 2026-09-17) |
| req-grid-service-delete-cascade-plan | [Cascade Plan Before Apply](#cascade-plan-before-apply) | Backlog | Read-only `plan_delete_cascade`, gated by its own `grid.plan_delete_cascade` capability, returns the closure a cascade would retire, the edges it would end, and what blocks it, with an opaque plan token; apply can refuse a stale plan |
| req-grid-service-delete-future | [Deferred Delete Policy Design](#deferred-delete-policy-design) | Refactoring | Explicit deferral narrowed now that tombstones are specified here; cascade policy now specified in `req-grid-service-delete-cascade` |


### Baseline Delete Semantics
----
RID: `req-grid-service-delete-baseline`

Status: `Implemented`

The minimum delete contract for TAP is that deleting a node removes its associated entity and any associated edges, preserving the graph's baseline integrity guarantees.

#### Status Details
`delete_node()` routes through `write_batch()` / `_execute_write_pipeline()`. The pipeline now uses tombstone semantics (see `req-grid-service-delete-tombstone`): `deleted_at` is set on the entity and cascade-tombstones connected edges. Physical rows are not removed.

#### Implementation
Baseline guarantees:

- deleting a `BaseModel`-backed node deletes its associated `Entity`
- deleting that entity removes associated edges through cascade behavior
- deleting an edge removes its backing entity

Delete semantics beyond this baseline, such as configurable cascade policy, soft delete, or selective unlinking behavior, are deferred.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-baseline-1 | Node Delete Removes Entity | Implemented | Deleting a node through the service layer removes its associated entity. | |
| req-grid-service-delete-baseline-2 | Node Delete Removes Related Edges | Implemented | Deleting a node through the service layer removes related edges via the established cascade path. | |
| req-grid-service-delete-baseline-3 | Edge Delete Removes Backing Entity | Implemented | Deleting an edge through the service layer removes its backing entity. | |

#### Future
Define whether edge removal should also support unlink-only semantics separate from full delete.

### Tombstoned Delete Semantics
----
RID: `req-grid-service-delete-tombstone`

Status: `Implemented`

The delete contract for TAP uses tombstoned lifecycle transitions rather than immediate destructive removal from canonical tables. Delete remains a service-layer operation and preserves historical existence for later time-travel and audit features.

#### Status Details
`Entity.deleted_at` (nullable, indexed) marks tombstoned entities. `delete_node()` and `delete_edge_by_entity()` set `deleted_at` via `_execute_write_pipeline`. `BaseModel.objects` (LiveManager) excludes tombstoned entities from default queries. `BaseModel.all_objects` provides unfiltered access. Edge tombstone cascade: when a node is tombstoned, all live edges at either endpoint are also tombstoned atomically. Write prohibition: patch/replace verbs on a tombstoned entity raise `ServiceConflictError` with code `"conflict"`. Replay: a delete of an already-tombstoned target succeeds and writes nothing — the tombstone is the final lifecycle event and a retry must not move it (`-6`, Issue# 575 - tap).

#### Implementation
The tombstoned delete contract is:

1. Canonical nodes and edges carry `deleted_at`, where `NULL` means still live.
2. Service-layer delete sets `deleted_at` rather than physically removing canonical rows during ordinary delete operations.
3. The delete transition is recorded in history as the final lifecycle event for that object.
4. Normal current-state read/search/write service paths exclude tombstoned objects by default.
5. Historical service paths may still reconstruct tombstoned objects for points in time before `deleted_at`.
6. Edge visibility must be sanity-checked against endpoint existence so service-layer graph reads do not return dangling edges in either current or historical modes.

This requirement defines normal product delete behavior. Hard-delete maintenance or archival compaction, if needed later, should be treated as a separate operational concern.

#### Development
Tombstoning belongs in the delete spec because it is fundamentally a service-layer lifecycle decision:

- what delete means
- what current reads should hide
- what history should preserve

History and time travel then build on that lifecycle contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-tombstone-1 | Deleted At Field | Implemented | Canonical service-managed deletes use `deleted_at` with `NULL` meaning still live. | `Entity.deleted_at` nullable DateTimeField with db_index |
| req-grid-service-delete-tombstone-2 | Delete Uses Tombstone Transition | Implemented | Ordinary service-layer delete transitions set tombstone state instead of physically removing canonical rows. | `_execute_write_pipeline` sets `deleted_at` via `.update()` |
| req-grid-service-delete-tombstone-3 | Current Reads Exclude Tombstones | Implemented | Default service-layer current-state reads and searches do not return tombstoned objects. | `LiveManager` on `BaseModel.objects` filters `entity__deleted_at__isnull=True` |
| req-grid-service-delete-tombstone-4 | Delete Preserved For History | Proposed | Tombstoned deletes remain reconstructible through history/time-travel for timestamps before `deleted_at`. | Rows persist; time-travel query spec is backlogged |
| req-grid-service-delete-tombstone-5 | Edge Endpoint Sanity | Proposed | Service-layer graph reads do not return an edge unless its endpoints are valid in the requested visibility mode. | Deferred to graph read spec |
| req-grid-service-delete-tombstone-6 | Repeat Delete Is A Silent No-Op | Implemented | Deleting an already-tombstoned node or edge again succeeds and writes nothing: `deleted_at`, `updated_at` and `Entity.version` are unchanged, no second retirement `BatchEvent` is recorded, the target's edges are left as the first delete left them, and `cascade="contained"` from a tombstoned root walks nothing (its live children stay live). The result carries a warning starting `noop_already_tombstoned`. Holds through `delete_node`, `delete_edge_by_entity` and a raw `WriteOperation`; a stale `entity_expected_version` still conflicts first (`req-grid-service-delete-occ-5`), and an invalid reason is still refused. The decision is made under a row lock: every delete takes `SELECT ... FOR UPDATE` on its target Entity (OCC or not), so two concurrent deletes of one live node retire it once — the second waits, re-reads the committed tombstone and no-ops. The warning names the token and the id only, never the retirement time. | Issue# 575 - tap. Retry-safety: a caller retrying after a timeout must not create history. The same rule `req-grid-service-delete-cascade-3` applies to an already-retired child, applied at the root. `tap_grid/tests/test_delete_cascade.py::TestDeleteReplay`, `::TestDeleteReplayConcurrent` (two threads, one tombstone, one event, one version bump). |

#### Future
Later work may add richer lifecycle states or explicit archive maintenance flows without redefining tombstone semantics as the default delete behavior.


### Delete Scope And Wrappers
----
RID: `req-grid-service-delete-scope`

Status: `Implemented`

Delete operations are exposed through the same explicit service-layer entry points as other writes.

#### Status Details
`delete_node(target)` and `delete_edge_by_entity(target)` both accept entity UUIDs and route through `write_batch()`. They participate in the same batching, dry-run, error taxonomy, and response envelope conventions as other write verbs.

Note: `delete_edge_by_entity` is the spec-compliant pipeline-based entry point for edge deletes. The legacy compat wrapper `delete_edge(edge: Edge)` is deprecated and kept only for backward compatibility with existing callers.

#### Implementation
Delete entry points:

- `delete_node(target, ...)` — removes node + Entity spine via write pipeline
- `delete_edge_by_entity(target, ...)` — removes edge + backing Entity via write pipeline
- `write_batch([WriteOperation(verb="delete_node", target=...)])` — batch delete

Delete results use the same structured `WriteResult` envelope and `ServiceError` taxonomy as other writes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-scope-1 | Node Delete Entry Point | Implemented | The service layer defines a public node delete entry point. | `delete_node(target)` |
| req-grid-service-delete-scope-2 | Edge Delete Entry Point | Implemented | The service layer defines a public edge delete entry point. | `delete_edge_by_entity(target)` — naming differs from spec due to legacy compat |
| req-grid-service-delete-scope-3 | Delete Uses Shared Write Contract | Implemented | Delete operations participate in the same batching, error, and response conventions as other writes. | |

#### Future
Rename `delete_edge_by_entity` to `delete_edge` once the legacy compat wrapper is removed.


### Service-Layer Purge
----
RID: `req-grid-service-purge`

Status: `Implemented`

A DEBUG-only escape hatch for hard-deleting a single entity along with its touching edges and history rows. The default delete contract remains tombstone (`req-grid-service-delete-tombstone`); purge is the explicit, narrow exception when an operator needs the entity gone rather than hidden — primarily for dev resets where accumulated tombstones obscure the grid state under test.

#### Status Details
`purge_node(entity_id, *, caller_context, reason)` lives in `tap_grid/services.py` and is fronted by the `manage.py purge_entities` management command. Both refuse to run unless Django's `DEBUG` setting is `True`.

#### Implementation

Function shape:

```python
def purge_node(
    entity_id: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    reason: str,
) -> PurgeResult:
    """Hard-delete an entity, its touching edges, and history rows."""
```

What gets deleted in one purge_node call:

1. The typed BaseModel row identified by `entity_id` (cascades from the Entity-spine delete via the OneToOneField).
2. The typed model's `historical_X` rows for that entity_id.
3. Every Edge row touching the entity at either end (both directions) — Edge typed rows, their history, and their Entity spines.
4. `BatchEvent` rows referencing the purged entity (and the purged edges), so no orphan event rows survive.
5. The Entity-spine row itself.

What is NOT deleted:

- Neighbor entities at the other end of any touching edge. Purge cascades to edges, not to nodes. (Spec note: full cascade-delete policy is still open — see [Deferred Delete Policy Design](#deferred-delete-policy-design). For now, purge is deliberately narrow.)
- `Batch` rows. A `Batch` is itself a first-class entity; purging a typed row that came from a batch does not remove the batch.
- Other entities of the same type. Purge is per-entity. The CLI's `--all-of-type` flag enumerates entities and calls `purge_node` once per entity_id.

`reason` is a required string argument and is captured in the application log alongside the entity_id, entity_type, and the caller_context actor. There is no `PurgeLog` table in v0; the application log is the only durable trace. A future requirement may add a `PurgeLog` table if/when production use cases (GDPR erasure, bad-ingest rollback) land.

`INTERNAL_ONLY` does NOT block purge. The flag prevents accidental writes through the generic CRUD verbs (`create_node` et al.); purge is deliberate and explicit, so the same protection is unnecessary. CollectionJob, Batch metadata, etc. are all purgeable through this path.

#### DEBUG-only invariant

**Invariant:** `purge_node` and `manage.py purge_entities` are permitted if and only if Django's `DEBUG` setting is `True` at the moment of invocation. No alternate flag, environment variable, settings key, or caller-context field enables purge in any other configuration. This mirrors the invariant on `req-grid-import-grift-sweep-purge` so the "purges are DEBUG-only" rule reads consistently across both surfaces.

When `DEBUG` is `False`, calling `purge_node` raises `ServiceConflictError` with code `purge_refused_production`. The CLI surfaces the same error and exits non-zero.

#### CLI: `manage.py purge_entities`

```
manage.py purge_entities --entity-type <type> (--all-of-type | --entity-id <uuid>...) --reason "<text>"
```

- `--entity-type` (required): the registered entity type slug (e.g. `ksi_indicator`). Scoping by type makes "purge every entity of this type" unmistakable in intent.
- `--all-of-type` (mutually exclusive with `--entity-id`): purge every entity of `--entity-type` currently on the grid (tombstoned or live). Reads as "purge every <type> entity", NOT "purge everything in the database".
- `--entity-id` (mutually exclusive with `--all-of-type`, repeatable): purge specific entity IDs. Each ID must match `--entity-type`; mismatches abort the run before any writes.
- `--reason` (required): free-form text recorded in the application log alongside each purge.

The command iterates the targets and calls `purge_node` once per entity. Output is one line per entity (`purged: <entity_type> <entity_id>`) plus a final tally.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-purge-1 | DEBUG-only gate | Implemented | `purge_node` raises `ServiceConflictError` with code `purge_refused_production` when `settings.DEBUG` is `False`. The CLI surfaces the same error. | Mirrors `req-grid-import-grift-sweep-purge`'s gate. |
| req-grid-service-purge-2 | Edge-only cascade | Implemented | Purging an entity hard-deletes every Edge touching it at either end, including the Edge's history rows, its `BatchEvent` rows, and its Entity-spine row. Neighbor entities at the far end of those edges are NOT purged. | Full cascade-delete policy remains deferred per [Deferred Delete Policy Design](#deferred-delete-policy-design). |
| req-grid-service-purge-3 | History rows go with the entity | Implemented | The typed BaseModel's `historical_X` rows for the purged entity_id are hard-deleted alongside the Entity spine. | django-simple-history's history table FK does not enforce cascade by itself; `purge_node` deletes explicitly. |
| req-grid-service-purge-4 | BatchEvent rows go with the entity | Implemented | Every `BatchEvent` referencing the purged entity (or any purged edge) is hard-deleted so no orphan event rows survive the purge. | |
| req-grid-service-purge-5 | INTERNAL_ONLY does not block | Implemented | `INTERNAL_ONLY` entity types are purgeable through `purge_node`. The flag is about preventing accidental generic-CRUD writes, not about preventing deliberate hard-delete. | |
| req-grid-service-purge-6 | Reason required | Implemented | `purge_node`'s `reason` argument is required and captured in the application log alongside the entity_id, entity_type, and actor. No purge log row in v0. | |
| req-grid-service-purge-7 | CLI scope by type | Implemented | `manage.py purge_entities --entity-type <type>` is required. `--all-of-type` means "every entity of this type", never "every entity in the database". | |
| req-grid-service-purge-8 | CLI mutual exclusion | Implemented | `--all-of-type` and `--entity-id` are mutually exclusive. Mismatched `--entity-id` / `--entity-type` aborts before any writes. | |

#### Future

- **Chokepoint with the GRIFT batch sweep purge.** The GRIFT importer's `_apply_sweep_purge` path (`req-grid-import-grift-sweep-purge`) currently inlines the hard-delete sequence. A future refactor should route per-entity purge through `purge_node` so that both surfaces share one hard-delete primitive, one DEBUG gate, one log format, and any future changes (PurgeLog, cascade policy revisions) land in a single place. The GRIFT sweep would retain its batch-scoped ownership guardrails (Guardrail A / B) on top of the shared per-entity primitive. Tracked by this Future note and a sibling note on `req-grid-import-grift-sweep-purge`.
- **PurgeLog table.** When the first production use case arrives (GDPR right-to-erasure, bad-ingest rollback), add a `PurgeLog` row per purge with no FK back to the purged entity, so the application can answer "was entity X ever here, when did it leave, and why" without resurrecting the row.
- **REST exposure.** Not in v0; revisit when TAP has a real auth + permissions model that can distinguish "operator with purge rights" from any other actor.

### Service-Layer Edge Purge
----
RID: `req-grid-service-purge-edge`

Status: `Implemented`

TAP needs a DEBUG-only hard-delete primitive for a single Edge entity. This is the edge sibling of `purge_node`, and is required before GRIFT `purges.edges[]` can route through the service layer rather than duplicating hard-delete logic in the importer.

#### Implementation

Function shape:

```python
def purge_edge(
    entity_id: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    reason: str,
) -> PurgeResult:
    """Hard-delete one Edge entity and its history/event rows."""
```

What gets deleted in one `purge_edge` call:

1. The Edge typed row identified by `entity_id`.
2. The Edge's Entity-spine row.
3. The Edge's `HistoricalEdge` rows.
4. `BatchEvent` rows referencing the purged Edge.

What is NOT deleted:

- Either endpoint node.
- Any other edge touching either endpoint.
- Any Batch row.

`purge_edge` enforces the same DEBUG-only invariant as `purge_node`: it is permitted if and only if Django `DEBUG` is `True`, with no alternate override. It requires a non-empty `reason` and captures that reason in the application log alongside the entity_id, actor, and edge endpoints when available.

`purge_edge` only accepts entities whose `entity_type == "edge"`. Calling it for a node entity raises a conflict error with a stable code such as `purge_edge_wrong_type`.

The `manage.py purge_entities` command should accept `--entity-type edge` once `purge_edge` exists, routing edge targets to `purge_edge` and non-edge targets to `purge_node`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-purge-edge-1 | DEBUG-only gate | Approved for Development | `purge_edge` refuses to run unless `settings.DEBUG` is `True`. | Same invariant as `purge_node`. |
| req-grid-service-purge-edge-2 | Edge type only | Approved for Development | `purge_edge` accepts only Entity rows with `entity_type == "edge"` and rejects node entities. | |
| req-grid-service-purge-edge-3 | Endpoint nodes survive | Approved for Development | Purging an edge hard-deletes only that edge and its own metadata/history; endpoint nodes survive. | |
| req-grid-service-purge-edge-4 | History rows go with the edge | Approved for Development | Edge history rows for the purged edge are hard-deleted. | |
| req-grid-service-purge-edge-5 | BatchEvent rows go with the edge | Approved for Development | BatchEvent rows referencing the purged edge are hard-deleted. | |
| req-grid-service-purge-edge-6 | Reason required | Approved for Development | A non-empty reason is required and logged with the purge. | |
| req-grid-service-purge-edge-7 | CLI routes edge purges | Approved for Development | `manage.py purge_entities --entity-type edge` routes each target through `purge_edge`. | |


### Optimistic Concurrency Parameter On Delete And Purge
----
RID: `req-grid-service-delete-occ`

Status: `Implemented`

Delete and purge verbs accept `entity_expected_version` per the OCC contract defined in `req-grid-service-batch-occ` (`spec-grid-service-batch.md`). This requirement documents the signatures and semantics specific to delete and purge surfaces; the general contract, error code, and conflict-handling rules live in the batch spec.

#### Implementation

Signatures gain `entity_expected_version`:

```python
def delete_node(
    target: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    reason: str | None = None,
) -> WriteResult: ...

def delete_edge_by_entity(
    target: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    reason: str | None = None,
) -> WriteResult: ...

def purge_node(
    entity_id: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    reason: str,
) -> PurgeResult: ...

def purge_edge(
    entity_id: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    reason: str,
) -> PurgeResult: ...
```

Behavior:

- Omitting `entity_expected_version` performs the delete or purge with no version check (current behavior).
- Setting `entity_expected_version` runs the verb through the service-layer Entity-row guard defined in `req-grid-service-batch-occ`. Tombstone delete updates the row after the guard passes; purge removes the row (and its history / BatchEvent / typed-row dependents per the purge contract) after the guard passes. If the guard fails, the verb returns a conflict result with the detail payload defined in `req-grid-service-batch-occ`.
- For tombstone deletes specifically: an already-tombstoned target where the caller's `entity_expected_version` matches the current version is a successful no-op (the delete verb is already idempotent against tombstoned targets; OCC does not change that). An already-tombstoned target where `entity_expected_version` does not match is a conflict, surfacing the version mismatch as usual.
- For purges: an already-tombstoned target is a valid purge target (purge removes the row entirely). The version check still applies — purging a tombstoned target whose version moved (e.g. someone restored the tombstone state under the operator's feet) is a conflict.

`purge_node` and `purge_edge` retain their DEBUG-only invariant; the version check is in addition to, not a replacement for, the DEBUG gate.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-occ-1 | Delete Verbs Accept Expected Version | Approved for Development | `delete_node` and `delete_edge_by_entity` accept `entity_expected_version: int \| None = None`. | |
| req-grid-service-delete-occ-2 | Purge Verbs Accept Expected Version | Approved for Development | `purge_node` and `purge_edge` accept `entity_expected_version: int \| None = None`. | DEBUG gate still applies. |
| req-grid-service-delete-occ-3 | Atomic Check-And-Mutate | Approved for Development | The version check is performed atomically with the delete or purge SQL statement. | Race window is zero. |
| req-grid-service-delete-occ-4 | Conflict Surfaces As Standard Error | Approved for Development | A version mismatch returns a result with `errors[0].code == "entity_version_conflict"` per `req-grid-service-batch-occ`. | |
| req-grid-service-delete-occ-5 | Tombstoned Idempotency Preserved | Implemented | An already-tombstoned target with matching `entity_expected_version` is a successful no-op for tombstone deletes; an already-tombstoned target with mismatching `entity_expected_version` is a conflict. | The no-op is `req-grid-service-delete-tombstone-6`'s: nothing on the row moves. Until Issue# 575 - tap the "no-op" bumped the version and rewrote `deleted_at`, and the test asserted only that the row was still tombstoned. `tap_grid/tests/test_occ.py::TestDeleteNodeOCC::test_delete_tombstoned_with_matching_version_is_noop_success`, `::test_delete_tombstoned_with_stale_version_is_conflict`. |


### Reason And Metadata On Delete
----
RID: `req-grid-service-delete-reason`

Status: `Partial`

`delete_node()` and `delete_edge_by_entity()` accept a typed **reason** and a structured **metadata** mapping, and forward both into the tombstone's batch event and its history record. A tombstone that records only a timestamp cannot be acted on, audited or reversed with confidence.

#### Status Details
Partial (2026-09-17): `delete_node()` and `delete_edge_by_entity()` take `reason` and `metadata`, the vocabulary is closed and refused at the boundary before any write, an omitted reason (`None`, never `""`) records `unspecified`, and the payload lands in the tombstone's `BatchEvent.metadata` — `tap_grid/tests/test_delete_cascade.py::TestDeleteReason`. AC -2 (history) is open: a tombstone writes no typed-model historical row today. Before this change `purge_node()` already required a non-empty free-text `reason`; the tombstone verbs accepted none. Both storage destinations already exist and one of them is already used for exactly this purpose by the GRIFT importer.

#### Implementation
Two destinations, both present today:

- **`BatchEvent.metadata`** — a JSONField described as "additional context". The GRIFT importer already writes `{"grift_operation": "delete", "reason": …}` there for imperative removals, so the structured record has an established home and shape.
- **`history_change_reason`** — django-simple-history's built-in field on every historical row, currently set by nothing in `tap_grid`. It takes the one-line human form, so a time-travel view can show *why* alongside *when*.

The reason is a **closed vocabulary** rather than free text, because a third state whose justification is unconstrained becomes a place to put discomfort rather than a fact: `dropped_from_observation` · `scope_withdrawn` · `cascaded` · `resolved` · `operator` · `grift_import` · `unspecified`.

**`operator` asserts a human acted, so it is never a default — RULED 2026-09-15.** An omitted reason records `unspecified`, which claims nothing about who or what decided. Defaulting to `operator` would let an automated, background or legacy caller mint a tombstone whose audit record names a person — a well-formed, present, false record, in the one place a false record is least recoverable. That the vocabulary already carries `grift_import` is the proof the distinction matters: non-human origins were always expected to name themselves. Three states, not two: a stated reason, `unspecified`, never a manufactured one. Metadata is structured and its shape is keyed by the reason — a reconciliation retirement carries its evidence strength, the scope statement it was decided under and the deciding run; a cascaded retirement additionally carries the parent it was a consequence of, and `forced: true` where an authority override was used.

Purge keeps its own free-text reason: a hard delete is an operator action described in prose, not a machine-classified lifecycle transition.

#### Development
Written after the reconciliation design established that a retirement's meaning lives entirely in its reason — the same absence renders as *deleted*, *made private*, *transferred* or *withdrawn from scope* depending on evidence the verb never sees, so the caller must state it and the record must keep it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-reason-1 | Reason reaches the batch event | Implemented | A tombstone written with a reason produces a `BatchEvent` whose `metadata` carries that reason and the supplied structured payload. | |
| req-grid-service-delete-reason-2 | Reason reaches history | Proposed | The tombstone's historical row carries `history_change_reason`. | Field exists and is unused today. **Found 2026-09-17:** a tombstone writes no typed-model historical row at all — the pipeline updates `Entity.deleted_at` on the spine and never saves the typed instance — so there is no row to carry the reason yet. Its own change. |
| req-grid-service-delete-reason-3 | Vocabulary is closed | Implemented | A reason outside the declared vocabulary — including an explicit empty or whitespace-only string — is refused with `invalid_reason` before any write, through the wrappers and a raw `WriteOperation` alike. | Issue# 576 - tap: `op.reason or UNSPECIFIED_REASON` let `""` pass as omission. `tap_grid/tests/test_delete_cascade.py::TestDeleteReason::test_an_explicit_blank_reason_is_refused_not_defaulted`. |
| req-grid-service-delete-reason-4 | Backwards compatible, and honest about it | Implemented | Existing callers that pass no reason continue to work, recording `unspecified` — never `operator`. Omission means `None`; an explicit `""` is not omission. A test asserts no code path defaults a reason to `operator`. | Additive parameter. Corrected 2026-09-15: the earlier wording defaulted to `operator`, which attributes an automated tombstone to a person. Making the reason mandatory was considered and rejected (it breaks callers for no audit gain over `unspecified`), as was restricting the default to named operator-only call sites (an allow-list that silently grows wrong). |

#### Future
When a retirement's reason needs to be queryable at scale rather than per-event, a denormalized reason column on the spine becomes worth considering; today the batch event is sufficient and avoids widening the spine.

---

### Contained-Subtree Cascade
----
RID: `req-grid-service-delete-cascade`

Status: `Partial`

`delete_node(target, cascade="contained")` retires the target **and everything reachable from it by a declared containment relation**, in one transaction. Relations not declared as containment are references: they are not followed, their edges are ended by the existing endpoint cascade, and their far nodes are left alone.

#### Status Details
Partial (2026-09-17): the make-it-work walk is built — `delete_node(..., cascade="contained")` over `CONTAINMENT_EDGES`, one transaction, cycle-safe, capped by `TAP_CASCADE_MAX_CLOSURE`, rolled back whole on any child's refusal, provenance naming the parent and the root — `tap_grid/tests/test_delete_cascade.py::TestContainedCascade`, `::TestContainmentDeclaration`; the Backlog rows below are the make-it-right and make-it-fast passes. **Down-scoped 2026-09-17 ("Cascade First").** This requirement had accumulated a preflight closure gather with authority over every type in the closure, a `cascade_force` capability with `forced: true` audit stamps, an integrity-findings subsystem and an `EXPLAIN`-checked retrieval bound before one cascade had run. What ships is the make-it-work walk: a dedicated containment declaration on the model, a recursive walk inside `delete_node`, one transaction, a visited set, a hard cap, and per-child authority with rollback on refusal. The rest is retained below as Backlog acceptance criteria — the make-it-right pass — so it is not re-derived; the make-it-fast pass is embedded paths checked against this walk (`tap#499`); the dry run is `req-grid-service-delete-cascade-plan` (Backlog). Narrows the deferral in `req-grid-service-delete-future` and supplies the mechanism `req-grid-entity-cascade` (Backlog) asks for. Django's machinery cannot serve here on two independent counts: there are no foreign keys between typed node tables (relationships are edge rows on the spine), and tombstoning never calls `Model.delete()`, so `on_delete` would never fire.

#### Implementation
**Declared on the model, beside the permission declaration — not inside it.** Each model declares `CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ()`: the edge types through which this node contains children. `OUTBOUND_EDGES` stays exactly what it is — the edge-permission mechanism — and carries no delete semantics (George, 2026-09-17). A guard asserts every declared containment edge type is also a permitted outbound edge type for that model, so the two declarations cannot drift apart. Imperative per-type hooks ("`on_retire` does what makes sense") were considered and rejected: they hide the descent table in code, so nobody can answer "what would this retire?" without reading every model, and they break the property that collection descent, the falsifier's fan-out and cascade read **one declaration**. An optional hook beside the declaration remains possible for a type whose retirement genuinely cannot be expressed as containment edges; it is never the mechanism.

**Containment versus reference.** The relations a cascade follows are declared, and the default for an undeclared relation is **not followed** — fail closed. This is deliberately the *opposite* default from edge-permission validation, whose union treats an unconstrained node as permitting everything (`tap#397`); cascade therefore runs on its own evaluator over `CONTAINMENT_EDGES` and never shares a permissive-when-unconstrained branch, because there "allow" means "retire".

**What the subtree includes.** Both declared and executed children. The rule that executed facts are never retired *on absence* protects an inference from a retention window; a cascade is not an inference but a consequence — if the container cannot be observed, neither can its runs, and leaving them live asserts otherwise. Cascaded retirements carry provenance naming the parent they were a consequence of, and inherit the parent's evidence rather than probing for their own.

**The walk.** Inside one `atomic` block: for each edge type in the target model's `CONTAINMENT_EDGES`, for each live child at the far end of such an edge from the target, `delete_node(child, cascade="contained", reason=<parent's reason>, metadata=<parent's metadata + consequence_of=<parent id>>)` — recursively, top-down. A visited set makes a cycle terminate. Already-retired children are skipped. A hard cap, `TAP_CASCADE_MAX_CLOSURE`, counts nodes retired in the walk; exceeding it raises `cascade_closure_too_large`, and because the block is atomic, nothing is written. Reference edges at every retired node are ended by the existing endpoint rule (`req-grid-service-delete-tombstone`), and their far nodes stay live.

**Authority, per child.** Each child goes through the same pipeline as any delete today — the outer batch's global write/delete capability check, the load, and the `INTERNAL_ONLY` refusal; the pipeline's own authorization step is a stub, so "per child" means *the same checks per node*, not a finer, per-child grant (Codex review, 2026-09-17). A refusal anywhere in the subtree raises, the transaction rolls back, and the target stays live — the same fail-safe outcome as a preflight, without the preflight. What is not built: gathering the closure first, checking authority over every edge ended (including reference edges crossing out of the subtree) and reporting the blocking types; and `cascade_force`. Both are Backlog below.

**A child with two containing parents** is retired with the first parent that cascades. The walk reads outgoing containment and tracks what it has seen; it does not inspect incoming containing edges, so **no warning names the second parent today** — that warning is Backlog with the integrity findings (Codex review, 2026-09-17: a claimed warning nothing emits is worse than none). The integrity findings this requirement once specified — cycles, multiple containing parents, a containing edge from a different perspective, the reparenting race — are Backlog; the reparenting race needs phase 5's freshness fence to be meaningful at all.

**Provenance and the shared path.** Every node and edge retired in the walk carries the same run, scope and reason in `BatchEvent.metadata`, plus the id of the parent it was a consequence of — nodes as `delete` events, the edges the walk ends as `unlink` events (Issue# 573 - tap). An operator's imperative GRIFT delete rides this same pipeline for a plain delete; GRIFT has **no cascade parameter yet**, so a cascade requested from GRIFT is Backlog (`-16`), and a reconcile verdict in phase 5 will take the identical path and produce the identical subtree.

#### Development
The shape is the mainstream one: a declared per-relation action (SQL's referential actions, Django's `on_delete`, Datomic's `isComponent` with recursive retraction, Kubernetes `ownerReferences`), applied top-down in one transaction, with an undeclared relation doing nothing. Every one of those is declarative; the systems that struggled with cascades struggled with imperative per-type deletes. The authority model in the Backlog rows follows the directory-service pattern — a single grantable subtree right that overrides child protections — rather than the permissive one where the schema declaration itself confers the authority.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-cascade-1 | Containment followed, references ended | Implemented | A cascade retires nodes reachable by declared containment; a node reachable only by a reference relation is untouched and its edge is ended. | |
| req-grid-service-delete-cascade-2 | Undeclared is not followed | Implemented | A relation absent from `CONTAINMENT_EDGES` is not traversed; cascade uses its own evaluator over that declaration, never the edge-permission union. | |
| req-grid-service-delete-cascade-3 | One transaction | Implemented | The whole subtree commits or none of it does; already-retired children are skipped idempotently. | |
| req-grid-service-delete-cascade-4 | Cancelled on refusal | Implemented | Lacking authority over any child in the walk, the cascade rolls back and writes nothing — including the target. | The blocking-types report is `-8`'s Backlog half. |
| req-grid-service-delete-cascade-5 | Force is recorded | Backlog | With `cascade_force`, the cascade proceeds and every retired node and edge records `forced: true`. | Make-it-right. |
| req-grid-service-delete-cascade-6 | Closure before ending edges | Backlog | The traversal gathers the full closure before ending any edge required to discover it. | Make-it-right; the walk ends edges as it goes and relies on the transaction. |
| req-grid-service-delete-cascade-7 | Reparenting race | Backlog | A child reparented to a new container during an old container's cascade is not retired by that cascade. | Needs the phase-5 freshness fence. |
| req-grid-service-delete-cascade-8 | Every ended edge is authorized | Backlog | Authority is checked over each edge the cascade ends, including reference edges whose far endpoint lies outside the contained subtree, and a refusal names the blocking types. | Make-it-right. **Not a regression:** this was a Proposed AC that no code ever implemented — today's endpoint cascade (`tap_grid/services/_impl.py`, the delete branch) ends incident edges with a spine update and checks no per-edge authority; what gates every ended edge is the actor-level delete capability `write_batch` requires for the whole batch. Moving the per-edge check to Backlog changes the plan, not the code's behaviour (Codex on #562). |
| req-grid-service-delete-cascade-9 | Force overrides authorization only | Backlog | With `cascade_force`, the freshness fence, integrity checks and root authority still apply and can still cancel the cascade. | With `-5`. |
| req-grid-service-delete-cascade-10 | No AI actor holds force | Backlog | `cascade_force` is never granted to an AI actor, and a grant attempt is refused at the capability boundary rather than at use. | Stands the day `-5` is built; `tap_ai` must not write core graph state in v0. |
| req-grid-service-delete-cascade-11 | Bounded work | Implemented | A walk that would retire more than `TAP_CASCADE_MAX_CLOSURE` nodes raises `cascade_closure_too_large` and, the block being atomic, writes nothing. | The retrieval bound (`LIMIT remaining + 1`, `EXPLAIN`) is `-15`. |
| req-grid-service-delete-cascade-12 | Declared on the model, not on permissions | Implemented | `CONTAINMENT_EDGES` is a dedicated declaration; a guard fails if it names an edge type the model's `OUTBOUND_EDGES` does not permit; `OUTBOUND_EDGES` carries no cascade semantics. | Ruled 2026-09-17. |
| req-grid-service-delete-cascade-13 | Cycle-safe | Implemented | A cycle in the declared containment graph terminates the walk without error; each node is retired once. | |
| req-grid-service-delete-cascade-14 | Provenance names the parent | Implemented | Every node and edge retired by the walk records the run, scope, reason and the parent it was a consequence of in `BatchEvent.metadata` — nodes as `delete` events, ended edges as `unlink` events, an edge touched at both endpoints once; a plain GRIFT delete rides the same pipeline and produces the same records. | `test_delete_cascade.py` (`test_provenance_names_the_parent_and_the_root`, `test_edges_ended_by_the_walk_record_provenance_too`, `test_inbound_reference_edges_and_both_endpoints_record_once`). Edge events added for Issue# 573 - tap. |
| req-grid-service-delete-cascade-16 | Cascade from GRIFT | Backlog | An imperative GRIFT removal can request `cascade="contained"` and produces the identical subtree and records as the service call. | The importer builds plain `delete_node` operations today and has no cascade parameter; the schema and parameter work is deferred (PR# 568 - tap body; Codex review 2026-09-17). |
| req-grid-service-delete-cascade-17 | Declared edge types resolve | Implemented | Every edge type a model names in `OUTBOUND_EDGES`, `INBOUND_EDGES` or `CONTAINMENT_EDGES` is a defined edge type — a loaded plugin manifest's `.edge.json` or a core edge — checked after every app is ready (Django system check `tap_grid.E004`, an Error) and mirrored per plugin at author time by `validate_plugin`'s `edge-declarations` check; a renamed or removed edge definition is caught at boot and in the plugin's own CI rather than silently retiring nothing. | `tap/edge_declarations.py` (the one predicate, stdlib), `tap_grid/checks.py::check_edge_declarations_resolve`, `tap_plugins/validate/service.py::_check_edge_declarations`; `tap_grid/tests/test_checks.py::TestEdgeDeclarationsResolve`, `tap_plugins/tests/test_validate_edge_declarations.py`, `tap/tests/test_edge_declarations.py`. Issue# 583 - tap. |
| req-grid-service-delete-cascade-18 | Unresolved declarations may warn at boot, by operator choice | Backlog | An operator-selected, per-plugin waiver (never plugin-selected, with a mandatory reason, like the FIPS waiver) lets a stack whose model names an unresolved edge type boot with the failure surfaced as a warning users actually see, the unresolved containment edge treated as a reference until fixed; the default stays the `tap_grid.E004` Error. | Ruled Backlog by George 2026-09-18 (Issue# 591 - tap): pending a user-facing warning surface — a Django Warning scrolls past in boot output, which is exactly how a false declaration would reach production. The blast-radius concern: a plugin owned by someone else, updated under you, stopping an instance at its next boot. |
| req-grid-service-delete-cascade-15 | Bounded retrieval | Backlog | Every adjacency fetch is issued with `LIMIT remaining + 1` on an index-backed path; on a fixture with fan-out far above the cap, no query returns more than `cap + 1` rows and `EXPLAIN` shows an early-stopping plan. | Make-it-fast, with `tap#499`. |

Previewing a cascade before applying it is specified separately, as `req-grid-service-delete-cascade-plan` (Backlog).

#### Future
- **Integrity findings** for cycles, multiple containing parents and cross-perspective containing edges, surfaced as findings rather than a warning line.
- **Background propagation.** The specified behaviour is foreground: the subtree is one transaction. Should a cascade ever need to span an owner rather than a repository, the escape hatch is to retire the container immediately and sweep its dependents asynchronously under the same reason — safe precisely because the reason field makes the deferred work identifiable.
- **Scoped cascade authority** — restricting an actor to named types or dimensions rather than all-or-force.
- **Orphan semantics.** The third verb (`orphan` — leave the child live, drop the containing edge) is named but unspecified; nothing needs it yet.
- **Lifting the declaration onto the edge type** in the registry (the meta-graph), so descent, fan-out and cascade read it from one place without a per-model tuple.

---

### Cascade Plan Before Apply
----
RID: `req-grid-service-delete-cascade-plan`

Status: `Backlog`

`plan_delete_cascade(target, cascade="contained")` returns what `delete_node(target, cascade="contained")` would do, and writes nothing. `delete_node` then accepts that plan's token as `expected_plan` and refuses to proceed if the closure has changed since.

#### Status Details
**Backlog (ruled 2026-09-17): deferred until a working paths-based cascade exists.** The design below is kept as the record. It went through nine review rounds on #500 and is settled, but it is not on the make-it-work path.

Nearly every finding in those rounds came from two properties only a dry run has. It **shows a closure to a caller** who may not be authorized over all of it, which produced the redaction, witness paths, existence flags and oracles. It also **links plan and apply across a gap in time with a token**, which produced the MAC, nonce, read set and staleness. A cascade applied under delete authority, all-or-nothing, with refusals going to the audit record, has neither property.

Two things belong to `req-grid-service-delete-cascade` whether or not a dry run is ever built, and both are specified there: bounded fan-out on the closure walk (`req-grid-service-delete-cascade-11`), and the cascade's own integrity cases.

Table-vs-path agreement (tap#499) does **not** go through this verb. It is an internal test that calls the one closure function for both implementations directly and compares node and edge sets. That test has no caller, redaction or token. Implementation is tracked as tap#527, which is also backlogged.

#### Implementation
**Why `dry_run` is not this.** Every write verb, `delete_node` included, already takes `dry_run=True`: the operation runs inside the transaction and is rolled back. That answers "would this succeed?" and nothing more — `WriteResult` carries no list of what went with the target — and it pays the full write cost of a subtree only to discard it. A plan answers "what would this take with it?", by reading.

**One derivation.** The plan is the first two phases the cascade already specifies — gather the closure before ending any edge (`req-grid-service-delete-cascade-6`), then check authority over every type and edge in it (`-4`, `-8`) — returned instead of applied. Apply is plan plus write, through the same function. A preview computed by a separate traversal would be a second copy of the fact and could disagree with the delete it claims to describe, which is worse than having no preview.

**What a plan carries.**
- The target, and its version.
- **Retired nodes**, each with the containing parent that brought it into the closure.
- **Ended edges**, each marked containment or reference, and whether a reference edge crosses out of the subtree.
- **Blocking types**: the types and edges the actor lacks authority over — exactly what a refused apply would record — and whether `cascade_force` would be required.
- **Integrity findings**: a containment cycle, a child with two containing parents, a containing edge in another perspective. Surfaced at plan time, where a human or a caller can act on them, rather than only as an apply-time cancellation.
- **A plan token**: a fresh random nonce plus a **detached** MAC, and nothing else. The token string is `<nonce>.<mac>`. The nonce is **at least 128 bits from a CSPRNG** (`secrets.token_bytes(16)` or OS randomness, never a general-purpose PRNG); a short or predictable nonce would eventually repeat and let two plans of one graph produce the same token. The MAC is `django.utils.crypto.salted_hmac(<dedicated salt>, <MAC document>, algorithm="sha256")`. The MAC document is `tap_grid.natural_key.canonicalize({"nonce": <hex>, "actor": <id>, "target": <entity_id>, "closure": <members>})`. Every value is a string, which keeps the document inside `canonicalize`'s declared `str | int` domain; that domain is deliberately not widened (its docstring routes any widening through a versioned derivation, tap#475). `<members>` is the `<entity_id>:<version>` pair of **every entity the closure function read to produce the plan**, sorted and joined with `,`. That is its whole read set: every node apply would retire, every edge apply would end (containment and reference alike), and every node or edge it only *inspected*, such as a containing edge in another perspective that produces an integrity finding or a refusal instead of being ended. Binding the read set rather than the action set closes the class: anything that could change what the plan shows changes the token. Edges are bound by their own entity rows, not through their endpoints. A version increments only on the entity that was itself mutated (`req-grid-history-version-2`), so creating a reference edge leaves both endpoints' versions untouched. If only nodes were bound, apply could end an edge the caller never saw in the plan. That join is unambiguous because a UUID's text form and a base-10 version contain neither `:` nor `,`. Reusing the natural key's canonical JSON form means no second hand-rolled serialization exists to disagree with it. It is HMAC under `SECRET_KEY`, so no new secret kind is needed.
  - **The closure is never serialized into the token.** Django's `signing.dumps` / `Signer.sign` must **not** be used here: they authenticate a payload but do not encrypt it, and the payload base64-decodes straight out of the token, which would hand the caller exactly the unreadable ids and versions `-5` forbids. The actor, target and closure are inputs to the MAC only; apply re-derives them server-side.
  - **`algorithm="sha256"` is stated because `salted_hmac` defaults to SHA-1.**
  - **The nonce is why tokens can't be compared.** Two plans of an unchanged graph produce different tokens, so comparing tokens reveals nothing. A bare digest over closure ids would be both a change oracle and an offline membership test, because entity ids are UUIDv7 and partly guessable.

**Apply against a plan.** `delete_node(target, cascade="contained", expected_plan=<token>)` takes the nonce from the token, recomputes the closure inside its transaction, recomputes the MAC from that nonce, the **calling** actor, the target and the fresh closure, and compares it to the token's MAC in constant time. On a mismatch it writes nothing and returns `cascade_plan_stale`, without saying which part of the closure changed. **Authority is checked before staleness.** Authority over the root, the closure and every ended edge (`req-grid-service-delete-cascade-4`, `-8`) is evaluated first. An actor refused on authority gets that refusal and never `cascade_plan_stale`, so a retained token tells someone who cannot perform the delete nothing about whether the subtree changed. Because actor and target are MAC inputs rather than token contents, a token presented by a different actor or for a different target simply fails to match. Without `expected_plan` apply behaves as `req-grid-service-delete-cascade` specifies. This is the same check-and-mutate discipline as `entity_expected_version` (`req-grid-service-delete-occ`), widened from one entity to a closure. It fences the gap between a human confirming a plan and the delete running; it does not replace the concurrent-change validation the cascade already requires inside its own transaction.

**No disclosure beyond read authority.** A plan must not become a way to learn anything about entities the caller cannot read. That means their identities, and also their **existence, type, number and relationships**. The rule binds every field: retired nodes, ended edges, blocking types and integrity findings.
- **Only what is reachable through readable data is listed.** An entity appears in the plan only if a **fully readable witness path** runs from the target to it: every node and every edge along the way readable by the actor. A readable node reached only through something unreadable (`T → hidden H → readable G`) is not listed, because listing `G` as retired would disclose that it sits beneath `T` through a path the caller cannot see. Such an entity is suppressed into `incomplete_for_actor`, exactly as if it were unreadable itself. Unreadability therefore taints everything downstream of it that has no readable alternative route.
- **Everything unreadable collapses into one flag.** A plan whose closure touches anything the actor cannot read carries `incomplete_for_actor: true` and nothing else about it: no id, name, type, count or relationship. Naming only the *type* is not safe. That a type exists is public schema, but that one sits in *this* closure is graph data.
- **Blocking types** are listed only for entities the actor can read. If an unreadable entity would block apply, the plan says `blocked_by_unreadable: true` and nothing more.
- **Integrity findings are reported only when every participant is readable.** A finding that involves any unreadable participant is suppressed into `incomplete_for_actor`, not reported with the readable participants alone. A readable child reported as a "two-parent child" would disclose that its hidden second parent exists, and a cross-perspective finding would disclose a hidden edge.
- **Unreadable entities still feed the plan token**, so a change among them stales the plan. The only signal that reaches the caller is a refused apply, and the cascade's own concurrent-change validation would produce that anyway.

**Bounded work.** Planning writes nothing, and it must not become a way for any caller, even a deliberately granted one, to force unbounded traversal. The closure walk stops once it exceeds a configured cap, `TAP_CASCADE_MAX_CLOSURE`, and refuses with `cascade_closure_too_large`, naming the configured limit and nothing about the closure. **The bound covers database retrieval, not only closure cardinality.** Every adjacency fetch is issued with `LIMIT remaining + 1`, where `remaining` is the allowance left, so a single node with enormous fan-out cannot make one query materialize millions of edges before the walk notices it has exceeded the cap. The cap sits in the one closure function, so **apply enforces the same bound**: a plan never succeeds where apply would refuse, and the other way round. The refusal does reveal one bit, that the whole closure (including unreadable entities) is larger than the cap. That is accepted, because apply reveals the same bit and the threshold is operator configuration, not graph data. Per-actor rate limiting of plan requests belongs to the API layer (`tap_api`), which has no request throttle today. Rather than leave that as prose, **exposure is gated on it**: `plan_delete_cascade` may be callable in-process by trusted code, but it is not mounted on any API route, UI panel, or AI tool surface until a per-actor limit applies to it (`-9`).

**Who may plan: its own capability, `grid.plan_delete_cascade`.** Planning writes nothing, but it is not an ordinary read. It reports *delete* authority (blocking types, whether force is needed), it runs a server-side traversal on demand, and, under the accepted exception below, it discloses one bit about what the caller cannot see. So planning requires **`grid.plan_delete_cascade` and read authority on the target**, both.
- **Granted deliberately, never implied.** `grid.read` does not confer it. Neither `grid.delete` nor `cascade_force` implies it, nor it them. A role that deletes is granted both side by side, because an implied permission is the kind nobody notices they handed out. The capability also covers a role delete authority cannot: a reviewer who approves a destructive change without being able to perform it.
- **Refused before any work.** Without `grid.plan_delete_cascade` the call is refused before the closure is walked, so the refusal carries nothing about the closure, not even whether one exists.
- **Not read authority.** Holding `grid.plan_delete_cascade` does not widen what the actor may read; the redaction above applies to holders unchanged.
- **AI actors** may hold it only by explicit per-actor grant, never by default. A plan is how an AI helper reasons about a delete without performing one, and v0 AI is read-only. Applying stays governed by `req-grid-service-delete-cascade`, including `-10`: no AI actor holds `cascade_force`.
- **The name says cascade.** A bare `plan_delete` would read as previewing a single-node delete; the verb and the capability both carry `cascade` so neither can be mistaken for that (owner ruling, 2026-09-17).
- The capability is defined in the `tap_auth` registry (`tap_auth/tap_auth.capabilities.json`) when this is implemented, following the `<app>.<verb>` naming of `grid.delete` and `grid.purge`. `cares.self_test_collectors`, a strictly-less-privileged read-only preview beside `cares.run_collectors`, is the in-repo precedent.

**Accepted disclosure exception, holders of `grid.plan_delete_cascade` only.** Two signals are disclosed on purpose. They are recorded here so they aren't mistaken for leaks, or silently widened:
1. **Existence.** `incomplete_for_actor` and `blocked_by_unreadable` reveal that the target's closure contains at least one entity the caller cannot read, and in the second case that one would block apply. Removing them would make a plan look complete while apply still retires hidden nodes, and a misleading plan is worse than the bit.
2. **Change.** Planning the same target again can show those flags flip. A retained token cannot be used this way by anyone who can't perform the delete, because authority is checked before staleness (above).

Nothing further is disclosed: no id, name, type, count or relationship. Both signals reach only actors deliberately trusted with them, which is what makes the exception acceptable rather than a hole in `-5`.

#### Development
Plan-then-apply is the established pattern wherever a single call has a large blast radius: Terraform's `plan` and saved-plan `apply`, which refuses a plan that no longer matches state; Kubernetes server-side dry run; CloudFormation change sets; and, closest to this case, Django admin's delete confirmation page, which walks related objects and lists them before deleting. The stale-plan refusal follows Terraform: a confirmation is only meaningful for the state it was shown against.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-cascade-plan-1 | Plan writes nothing | Backlog | `plan_delete_cascade` opens no write transaction and creates no entity, history row, or `Batch` entity. | Distinct from `dry_run`, which writes and rolls back. |
| req-grid-service-delete-cascade-plan-2 | One derivation | Backlog | On an unchanged fixture, the set of nodes and edges a plan lists equals the set apply retires and ends; both come from one closure function, asserted by a test that would fail if either computed its own traversal. | |
| req-grid-service-delete-cascade-plan-3 | Stale plan refused | Backlog | Any of the following between plan and apply makes `delete_node(..., expected_plan=)` write nothing and return `cascade_plan_stale`: a child added, reparented, or version-bumped; **a reference edge added to or removed from a closure node**; a containment edge added or removed; or **a change to any entity the plan only inspected**, such as a cross-perspective containing edge that produced an integrity finding. | Edge cases added on review (Codex, round 6): endpoint versions do not move when an edge is created. |
| req-grid-service-delete-cascade-plan-4 | Blocking types match refusal | Backlog | On the same graph and actor, the blocking information a plan reports is identical to what a refused apply **returns to the caller**. Both are redacted the same way (readable blocking types named, `blocked_by_unreadable` otherwise), because both come from one redaction function. The unredacted blocking types go only to the operator-visible audit record that `req-grid-service-delete-cascade-4` requires, never to the caller on either path. | Reconciled with `-5` on review (Codex, round 7): "exactly" had pitted the plan against an unredacted refusal record. |
| req-grid-service-delete-cascade-plan-5 | No disclosure beyond read authority | Backlog | For a fixture whose closure mixes readable and unreadable entities, including an unreadable second containing parent, a cross-perspective edge, and a readable node reachable only through an unreadable intermediary (`T → H → G`, `H` unreadable), the serialized plan contains no id, name, type, count or relationship of any unreadable entity, and does not list `G`. The same fixture with a second, fully readable path from `T` to `G` does list it. Integrity findings are suppressed whenever any participant is unreadable. The only signals are `incomplete_for_actor` and `blocked_by_unreadable`, which are the accepted exception, available only to `grid.plan_delete_cascade` holders. | Tightened across four review rounds on #500. |
| req-grid-service-delete-cascade-plan-6 | Integrity surfaced at plan time | Backlog | A cycle, a two-parent child, or a cross-perspective containing edge is reported in the plan. | |
| req-grid-service-delete-cascade-plan-7 | Opaque, unlinkable token | Backlog | A token is exactly a nonce of at least 128 CSPRNG bits and a detached HMAC-SHA256. Base64- or hex-decoding any part of it yields no closure entity id or version, which a test asserts against known ids. Two plans of an unchanged graph return different tokens; a token matches only for its own actor and target; closure matching inside apply is independent of traversal order. | Review on #500 rejected a deterministic caller-visible digest (a change oracle and membership test), then a `signing.dumps` token (its payload decodes out of the token). |
| req-grid-service-delete-cascade-plan-8 | Bounded work | Backlog | A closure exceeding `TAP_CASCADE_MAX_CLOSURE` stops the walk and returns `cascade_closure_too_large` naming only the limit; apply enforces the same cap through the same function. On a fixture where one node has far more children than the cap, no single query returns more than `cap + 1` rows, asserted on captured query row counts rather than on the refusal alone. Rows returned are not work done, so the same fixture's adjacency query is also checked with `EXPLAIN` to be index-backed and early-stopping (no sequential scan, no sort over the whole fan-out). | Row bound added on review (Codex, round 5): refusing correctly is not the same as bounding the work. |
| req-grid-service-delete-cascade-plan-9 | Exposure gated on throttling | Backlog | `plan_delete_cascade` is not reachable from an API route, UI panel, or AI tool surface unless a per-actor rate limit applies to that surface; a test asserts no such mount exists while the limit is absent. | Makes the throttling risk enforceable instead of a note. |
| req-grid-service-delete-cascade-plan-10 | Planning is its own capability | Backlog | An actor with `grid.read` on the target but no `grid.plan_delete_cascade` is refused before the closure is walked, and the refusal is identical whether or not the target has a closure. Neither `grid.read`, `grid.delete` nor `cascade_force` confers `grid.plan_delete_cascade`. | Owner ruling 2026-09-17. |
| req-grid-service-delete-cascade-plan-11 | Authority before staleness | Backlog | `delete_node(..., expected_plan=)` from an actor lacking authority over the closure returns the authority refusal whether or not the token is stale; `cascade_plan_stale` is only ever returned to an actor who could perform the delete. | Closes the retained-token change oracle for non-deleters (Codex, round 4). |

---

### Deferred Delete Policy Design
----
RID: `req-grid-service-delete-future`

Status: `Refactoring`

#### Status Details
Narrowed twice. Tombstone semantics moved into `req-grid-service-delete-tombstone`; cascade policy
moved into `req-grid-service-delete-cascade` (2026-09-15). What remains deferred is unlink-only edge
semantics (the `orphan` verb) and any configurable per-call policy beyond the declared containment
relations.

Delete policy beyond the baseline guarantees is explicitly deferred rather than left ambiguous.

#### Status Details
This requirement is being narrowed now that tombstone semantics are specified separately in `req-grid-service-delete-tombstone`.

#### Implementation
Deferred areas include:

- configurable cascade policies
- block versus allow semantics on delete
- archive compaction or hard-delete maintenance behaviors
- selective unlink behaviors
- plugin-specific delete hooks

This requirement exists to make the backlog explicit and prevent accidental implicit policy.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-future-1 | Remaining Rich Delete Policy Deferred | Refactoring | The delete spec explicitly defers richer policy decisions not yet covered by baseline or tombstone requirements. | |
| req-grid-service-delete-future-2 | Follow-On Delete Policy Still Anticipated | Refactoring | The specification records remaining future delete-policy work beyond baseline and tombstone semantics. | |

#### Future
When the dedicated delete policy spec is created, it should supersede this backlog requirement with concrete policy rules.


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
