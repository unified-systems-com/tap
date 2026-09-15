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
| req-grid-service-delete-reason | [Reason And Metadata On Delete](#reason-and-metadata-on-delete) | Proposed | `delete_node` carries a typed reason and structured metadata into the batch event and the history reason |
| req-grid-service-delete-cascade | [Contained-Subtree Cascade](#contained-subtree-cascade) | Proposed | `cascade="contained"` follows declared containment relations, atomically; cancelled on any authority refusal unless `cascade_force` is held |
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


### Reason And Metadata On Delete
----
RID: `req-grid-service-delete-reason`

Status: `Proposed`

`delete_node()` and `delete_edge_by_entity()` accept a typed **reason** and a structured **metadata** mapping, and forward both into the tombstone's batch event and its history record. A tombstone that records only a timestamp cannot be acted on, audited or reversed with confidence.

#### Status Details
Proposed. `purge_node()` already requires a non-empty free-text `reason`; the tombstone verbs accept none. Both storage destinations already exist and one of them is already used for exactly this purpose by the GRIFT importer.

#### Implementation
Two destinations, both present today:

- **`BatchEvent.metadata`** — a JSONField described as "additional context". The GRIFT importer already writes `{"grift_operation": "delete", "reason": …}` there for imperative removals, so the structured record has an established home and shape.
- **`history_change_reason`** — django-simple-history's built-in field on every historical row, currently set by nothing in `tap_grid`. It takes the one-line human form, so a time-travel view can show *why* alongside *when*.

The reason is a **closed vocabulary** rather than free text, because a third state whose justification is unconstrained becomes a place to put discomfort rather than a fact: `dropped_from_observation` · `scope_withdrawn` · `cascaded` · `resolved` · `operator` · `grift_import`. Metadata is structured and its shape is keyed by the reason — a reconciliation retirement carries its evidence strength, the scope statement it was decided under and the deciding run; a cascaded retirement additionally carries the parent it was a consequence of, and `forced: true` where an authority override was used.

Purge keeps its own free-text reason: a hard delete is an operator action described in prose, not a machine-classified lifecycle transition.

#### Development
Written after the reconciliation design established that a retirement's meaning lives entirely in its reason — the same absence renders as *deleted*, *made private*, *transferred* or *withdrawn from scope* depending on evidence the verb never sees, so the caller must state it and the record must keep it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-reason-1 | Reason reaches the batch event | Proposed | A tombstone written with a reason produces a `BatchEvent` whose `metadata` carries that reason and the supplied structured payload. | |
| req-grid-service-delete-reason-2 | Reason reaches history | Proposed | The tombstone's historical row carries `history_change_reason`. | Field exists and is unused today. |
| req-grid-service-delete-reason-3 | Vocabulary is closed | Proposed | A reason outside the declared vocabulary is refused at the boundary. | |
| req-grid-service-delete-reason-4 | Backwards compatible | Proposed | Existing callers that pass no reason continue to work, recording an `operator` reason. | Additive parameter. |

#### Future
When a retirement's reason needs to be queryable at scale rather than per-event, a denormalized reason column on the spine becomes worth considering; today the batch event is sufficient and avoids widening the spine.

---

### Contained-Subtree Cascade
----
RID: `req-grid-service-delete-cascade`

Status: `Proposed`

`delete_node(target, cascade="contained")` retires the target **and everything reachable from it by a declared containment relation**, in one transaction. Relations declared as references are not followed; their edges are ended by the existing endpoint cascade and their far nodes are left alone.

#### Status Details
Proposed. Narrows the deferral in `req-grid-service-delete-future` and supplies the mechanism `req-grid-entity-cascade` (Backlog) asks for — cascade expressed in terms of edge relationships rather than Django's FK `CASCADE`. Note that Django's machinery cannot serve here on two independent counts: there are no foreign keys between typed node tables (relationships are edge rows on the spine, so a collector would find nothing to cascade), and tombstoning never calls `Model.delete()`, so `on_delete` would never fire.

#### Implementation
**Containment versus reference.** The relations a cascade follows are declared, and the default for an undeclared relation is **not followed** — fail closed. This is deliberately the *opposite* default from edge-permission validation, whose union treats an unconstrained node as permitting everything (`tap#397`); cascade must therefore run on its own evaluator and must never share a permissive-when-unconstrained branch, because there "allow" means "retire".

**What the subtree includes.** Both declared and executed children. The rule that executed facts are never retired *on absence* protects an inference from a retention window; a cascade is not an inference but a consequence — if the container cannot be observed, neither can its runs, and leaving them live asserts otherwise. Cascaded retirements carry provenance naming the parent they were a consequence of, and inherit the parent's evidence rather than probing for their own.

**Atomicity and authority.** The closure is gathered first, before any edge needed to discover it is ended. The actor's authority is then checked over **every entity type in the closure and every edge being ended** — including reference edges that cross *out* of the contained subtree, because ending one of those changes a node the actor may have no authority over. On **any** refusal the transaction writes nothing — the target stays live too — recording the refusal with the blocking types named.

A `cascade_force` capability, granted deliberately and assignable to a collector actor, is narrower than "skip the checks": it bypasses the **child authorization** check only. Evidence, the freshness fence, the integrity checks (cycles, multiple containing parents, the reparenting race) and authority over the cascade's **root** all still apply — a forced cascade is an authorization override, never a correctness override. Because it overrides authorization, every node and edge in a forced subtree records `forced: true` beside its reason, so a forced retirement is queryable rather than merely inferable.

**Integrity cases that must be specified before use**: a cycle in the declared containment graph; a child with two containing parents; and a child whose containing edge belongs to a different perspective. One concrete race matters — a source object reparented between containers while the **old** container is mid-cascade must not have its newly observed subtree retired by the old container's pass — so application is validated against concurrent change, not only prepared against a snapshot.

#### Development
The shape is the mainstream one: a declared per-relation action (SQL's referential actions, Django's `on_delete`, Datomic's `isComponent` with recursive retraction, TypeDB's `@cascade`), gathered top-down and applied in one transaction, with an undeclared relation doing nothing. The authority model follows the directory-service pattern — a single grantable subtree right that overrides child protections — rather than the permissive one, where the schema declaration itself confers the authority.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-delete-cascade-1 | Containment followed, references ended | Proposed | A cascade retires nodes reachable by declared containment; a node reachable only by a reference relation is untouched and its edge is ended. | |
| req-grid-service-delete-cascade-2 | Undeclared is not followed | Proposed | A relation with no containment declaration is not traversed; cascade uses its own evaluator, not the edge-permission union. | |
| req-grid-service-delete-cascade-3 | One transaction | Proposed | The whole subtree commits or none of it does; already-retired children are skipped idempotently. | |
| req-grid-service-delete-cascade-4 | Cancelled on refusal | Proposed | Lacking authority over any type in the closure, the cascade writes nothing — including the target — and records the blocking types. | |
| req-grid-service-delete-cascade-5 | Force is recorded | Proposed | With `cascade_force`, the cascade proceeds and every retired node and edge records `forced: true`. | |
| req-grid-service-delete-cascade-8 | Every ended edge is authorized | Proposed | Authority is checked over each edge the cascade ends, including reference edges whose far endpoint lies outside the contained subtree. | |
| req-grid-service-delete-cascade-9 | Force overrides authorization only | Proposed | With `cascade_force`, the freshness fence, integrity checks and root authority still apply and can still cancel the cascade. | |
| req-grid-service-delete-cascade-6 | Closure before ending edges | Proposed | The traversal gathers the full closure before ending any edge required to discover it. | |
| req-grid-service-delete-cascade-7 | Reparenting race | Proposed | A child reparented to a new container during an old container's cascade is not retired by that cascade. | Review acceptance case. |

#### Future
- **Background propagation.** The specified behaviour is foreground: the subtree is one transaction. Should a cascade ever need to span an owner rather than a repository, the escape hatch is to retire the container immediately and sweep its dependents asynchronously under the same reason — safe precisely because the reason field makes the deferred work identifiable.
- **Scoped cascade authority** — restricting an actor to named types or dimensions rather than all-or-force.
- **Orphan semantics.** The third verb (`orphan` — leave the child live, drop the containing edge) is named but unspecified; nothing needs it yet.

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
