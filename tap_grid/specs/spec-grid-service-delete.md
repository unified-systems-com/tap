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
| req-grid-service-delete-future | [Deferred Delete Policy Design](#deferred-delete-policy-design) | Refactoring | Explicit deferral narrowed now that tombstones are specified here |


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
`Entity.deleted_at` (nullable, indexed) marks tombstoned entities. `delete_node()` and `delete_edge_by_entity()` set `deleted_at` via `_execute_write_pipeline`. `BaseModel.objects` (LiveManager) excludes tombstoned entities from default queries. `BaseModel.all_objects` provides unfiltered access. Edge tombstone cascade: when a node is tombstoned, all live edges at either endpoint are also tombstoned atomically. Write prohibition: patch/replace verbs on a tombstoned entity raise `ServiceConflictError` with code `"conflict"`.

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
| req-grid-service-delete-occ-5 | Tombstoned Idempotency Preserved | Approved for Development | An already-tombstoned target with matching `entity_expected_version` is a successful no-op for tombstone deletes; an already-tombstoned target with mismatching `entity_expected_version` is a conflict. | |


### Deferred Delete Policy Design
----
RID: `req-grid-service-delete-future`
Status: `Refactoring`

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
