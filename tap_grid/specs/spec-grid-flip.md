# Grid FLIP Specification

## Philosophy

FLIP (Field-Level Information Provenance) explains the auditable sources of the current canonical data on a TAP object. FLIP is intentionally scoped to present state: it tells us which batch is responsible for the current value of each service-writeable field path. If a caller wants to know how that provenance changed over time, they must consult history.

## Goals

|    |              |                                                                                         |
| :---: | ---       | ---                                                                                     |
| 1. | Current      | FLIP explains provenance for the currently stored canonical values                       |
| 2. | Simple       | FLIP remains lightweight enough to update in normal write paths                          |
| 3. | Immutable    | FLIP points at immutable batch records rather than mutable provenance blobs              |
| 4. | Independent  | FLIP does not require history reconstruction and does not depend on perspective storage   |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-flip-map | [FLIP Field-Path Map](#flip-field-path-map) | Implemented | Canonical objects store a field-path-to-batch mapping for current values |
| req-grid-flip-batch | [FLIP Batch Anchoring](#flip-batch-anchoring) | Implemented | FLIP points to immutable batch ids rather than duplicating source metadata |
| req-grid-flip-default | [FLIP Default-On Coverage](#flip-default-on-coverage) | Implemented | FLIP applies by default to all service-writeable fields on service-writeable model types |
| req-grid-flip-config-depr | [FLIP Config Deprecation](#flip-config-deprecation) | Implemented | Legacy FLIP enablement and field-selection config is deprecated until needed again |
| req-grid-flip-nested | [Nested Field-Path FLIP](#nested-field-path-flip) | Proposed | Nested JSON field-path provenance is reserved as a future capability |
| req-grid-flip-separation | [FLIP and History Separation](#flip-and-history-separation) | Implemented | FLIP answers present-state provenance only; historical provenance lives in history |
| req-grid-flip-retirement | [Retirement Is A FLIP-Tracked State Change](#retirement-is-a-flip-tracked-state-change) | Implemented | A tombstone records the batch that retired the object, on the object and on every edge it ends |
| req-grid-flip-change | [FLIP Moves Only On Change](#flip-moves-only-on-change) | Implemented | An entry moves when a write changes the value or first asserts the field; a write that repeats the stored value leaves it alone |

## Explanation

FLIP is a current-state provenance index attached to canonical objects. It should be fast to read, cheap to update during normal writes, and easy to explain: for any service-writeable field path on the current object, TAP can identify which batch last set that value. The batch then provides immutable audit context such as actor, source, metadata, and timing.

This deliberately does not make FLIP a full provenance ledger. The ledger already exists in batch records and history. FLIP is the shortcut that makes current provenance inexpensive and explicit.

### FLIP Field-Path Map
----
RID: `req-grid-flip-map`

Status: `Implemented`

Every service-writeable canonical object stores a field-path map describing the batch responsible for each currently tracked field value.

#### Status Details
Implemented. `flip_map` JSONField on `BaseModel`; updated by `batch_context` writes. Viewer surfaces FLIP rows via `object_view` in `tap_web/views.py`.

#### Implementation
The FLIP payload should be a JSON object or equivalent keyed by field path:

```json
{
  "ip_address": "0195f5c6-2c6f-7f8d-a631-1d1d6e6f6d4a",
  "service.banner": "0195f5c6-2c6f-7f8d-a631-1d1d6e6f6d4a",
  "owner.team": "0195f5c7-3a14-7488-b3da-6b1f3d1c2ef9"
}
```

Rules:

1. Keys are field paths, not just top-level field names.
2. Values are batch ids for the batch that last set the current canonical value at that field path.
3. The FLIP map lives with the canonical object whose current values it describes.
4. Updating a service-writeable canonical field updates the corresponding FLIP entry.

#### Development
Using field paths instead of only top-level field names keeps the model viable if TAP tracks provenance inside structured fields. This is worth deciding up front because changing FLIP key shape later would be painful.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-map-1 | Field Paths Not Just Field Names | Implemented | FLIP keys are stored as field paths so nested tracked values can be represented. | `flip_map` keys are dot-delimited field paths |
| req-grid-flip-map-2 | Current Value Mapping | Implemented | Every FLIP entry points to the batch responsible for the currently stored canonical value at that field path. | Values are batch UUIDs from `batch_context` |
| req-grid-flip-map-3 | Canonical Object Locality | Implemented | The FLIP map is stored on the canonical object it describes rather than in a detached side table for v1. | `flip_map` JSONField on `BaseModel` |

#### Future
If FLIP maps become large or need independent indexing, TAP may later split them into a dedicated table while preserving the same logical contract.

### FLIP Batch Anchoring
----
RID: `req-grid-flip-batch`

Status: `Implemented`

FLIP should anchor provenance to immutable batch records rather than duplicating actor, source, or timing metadata per field path.

#### Status Details
Implemented. `Batch` records in `tap_flip` are immutable once closed. FLIP map values are batch UUIDs; actor/source/timing are read from the batch at display time.

#### Implementation
The batch id referenced by FLIP is the immutable join point for provenance lookup. Batch records should supply:

1. Actor identity where available.
2. Source or tool metadata.
3. Operational timing such as batch start and close times.
4. Any additional immutable context needed for audit.

FLIP itself should not duplicate this metadata. Its job is only to identify the responsible batch for each tracked field path.

#### Development
This is a good layering boundary because batch is already designed as sub-grid immutable operational context. Reusing it avoids inventing a second provenance store that would drift from batch truth over time.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-batch-1 | Batch Id As Provenance Pointer | Implemented | FLIP entries point to batch ids rather than embedding full actor/source metadata inline. | `flip_map` values are batch UUIDs |
| req-grid-flip-batch-2 | Immutable Join Target | Implemented | The batch referenced by FLIP is immutable and suitable for audit joins. | `Batch` records are closed and not mutated after write |
| req-grid-flip-batch-3 | Shared Batch Reuse | Implemented | Multiple field paths updated by the same operation may legitimately point to the same batch id. | All fields saved in one `batch_context` share the same batch UUID |

#### Future
If TAP later needs to attribute current fields to a finer-grained unit than a batch, it may introduce a batch-event pointer while preserving batch as the minimum required join target.

### FLIP Default-On Coverage
----
RID: `req-grid-flip-default`

Status: `Implemented`

FLIP is a default-on capability for service-writeable model types. It applies to all service-writeable fields rather than requiring per-model enablement or explicit allow-lists.

#### Status Details
Implemented. `update_flip_map()` in `tap_grid/flip.py` derives tracked fields from `SERVICE_CRUD_SCHEMA` (union of create/patch/replace properties) rather than a per-model allow-list. Internal-only types are excluded. If no batch_id is active, stamping is silently skipped rather than raising an error. `is_flip_enabled()` returns True for any model with service-writeable fields that is not internal-only.

#### Implementation
The FLIP coverage contract is:

1. FLIP is on by default for service-writeable model types.
2. FLIP stamps all service-writeable fields.
3. "Service-writeable fields" means fields writable by callers through the model's published service schemas.
4. System-managed fields such as `entity`, `entity_id`, `batch_id`, `flip_map`, lifecycle timestamps, and other internal service-managed fields are excluded from FLIP stamping.
5. For `patch`, FLIP updates the fields the payload touched whose value changed, and a touched field asserted for the first time (`req-grid-flip-change`). A touched field whose stored value the payload repeats keeps its entry.
6. For `replace`, FLIP updates the fields of the replace surface whose value changed, and a field the payload names that is asserted for the first time (`req-grid-flip-change`). A field the payload does not name is stamped only when its reset to the default changed the stored value.
7. For `create`, FLIP updates the service-writeable fields established at creation time.

This requirement applies only to service-writeable model types. Internal-only model types are outside the default FLIP surface for generic writes because they are not writable through the standard service layer.

#### Development
This simplifies the architecture substantially:

- no per-model FLIP on/off switch
- no per-model allow-list to maintain
- one predictable provenance rule for user-writeable data

If TAP later finds a real need for exceptions, configuration can return as a deliberate feature rather than as leftover scaffolding.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-default-1 | Default On For Service-Writeable Types | Implemented | FLIP applies by default to model types writable through the standard service layer. | No per-model config needed |
| req-grid-flip-default-2 | All Service-Writeable Fields Stamped | Implemented | FLIP covers all service-writeable fields rather than an explicit allow-list. | Derived from `SERVICE_CRUD_SCHEMA` properties |
| req-grid-flip-default-3 | System Fields Excluded | Implemented | Service-managed/internal fields are excluded from default FLIP stamping. | `entity`, `batch_id`, `flip_map` etc. are never in `SERVICE_CRUD_SCHEMA` |
| req-grid-flip-default-4 | Patch Replace Create Semantics Defined | Implemented | FLIP stamping behavior for create, patch, and replace follows the service-write surface rather than ad hoc save behavior. | `changed_fields` controls partial vs full stamping |

#### Future
If a real need for configurable FLIP scope emerges later, TAP may reintroduce policy controls intentionally rather than preserving legacy config by default.

### FLIP Config Deprecation
----
RID: `req-grid-flip-config-depr`

Status: `Implemented`

Legacy FLIP configuration structures such as `DEFAULT_FLIP_CONFIG`, `FLIP_CONFIG`, explicit enable flags, and per-model field allow-lists are deprecated until a concrete need for them returns.

#### Status Details
Implemented. `DEFAULT_FLIP_CONFIG`, `_FLIP_REGISTRY`, `get_model_flip_config`, `is_batch_enabled`, `get_flip_fields`, and the per-model `FLIP_CONFIG` class variable have been removed from `tap_grid/flip.py` and all model definitions. `tap_grid/models.py` no longer calls `get_model_flip_config()` in `__init_subclass__`. The `FLIP_CONFIG` on `Batch` and `Character` (lotr plugin) has been deleted.

#### Implementation
The deprecation direction is:

1. Remove the requirement that FLIP be selectively enabled or disabled per model type.
2. Remove the requirement that models configure FLIP field allow-lists for ordinary service-writeable fields.
3. Keep the specification centered on default-on FLIP for service-writeable fields.
4. If a future need for FLIP configuration reappears, it should be reintroduced through a new requirement rather than by preserving dormant config surfaces indefinitely.

#### Development
This is a cleanup move. The old config shape looks increasingly like a holdover from pre-spec exploration rather than a justified architectural feature.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-config-depr-1 | Per-Model FLIP Enablement Deprecated | Implemented | The specification no longer requires per-model FLIP on/off configuration for ordinary service-writeable types. | `FLIP_CONFIG` removed from all models |
| req-grid-flip-config-depr-2 | Field Allow-List Config Deprecated | Implemented | The specification no longer requires per-model FLIP field allow-lists for ordinary service-writeable fields. | Fields derived from `SERVICE_CRUD_SCHEMA` |
| req-grid-flip-config-depr-3 | Reintroduction Requires New Requirement | Implemented | Any future return of explicit FLIP config must be justified by a new requirement rather than by keeping dormant config as the default architecture. | Legacy config infrastructure deleted |

#### Future
If nested JSON provenance, exception cases, or internal-only model nuances require configuration later, those should be introduced as narrow targeted policy requirements.

### Nested Field-Path FLIP
----
RID: `req-grid-flip-nested`

Status: `Proposed`

FLIP should eventually support nested field-path provenance inside structured JSON payloads, but this is not required for the first default-on implementation.

#### Status Details
Proposed future capability. Current first-pass behavior may treat structured fields such as `properties` as a single top-level FLIP-tracked field path.

#### Implementation
Future nested FLIP should support:

1. Addressing nested JSON paths within service-writeable structured fields.
2. Updating nested provenance paths during patch/replace semantics.
3. Preserving the same batch-anchored current-state semantics as top-level FLIP fields.

#### Development
This should be implemented the day it becomes a real problem, not before.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-nested-1 | Nested JSON Paths Reserved | Proposed | The FLIP spec explicitly reserves support for nested field-path provenance inside structured JSON fields. | |
| req-grid-flip-nested-2 | Top-Level Structured Field Fallback Allowed | Proposed | Until nested FLIP is implemented, structured fields may be treated as a single top-level FLIP-tracked field path. | |

### FLIP and History Separation
----
RID: `req-grid-flip-separation`

Status: `Implemented`

FLIP answers current provenance only. Historical provenance analysis belongs to the history layer.

#### Status Details
Implemented. FLIP map stores only the most recent batch per field path; no history replay is required to read current provenance. History system is tracked separately in `spec-grid-history.md`.

#### Implementation
The required semantics are:

1. FLIP always describes the current canonical object state.
2. A FLIP read must not require replaying or scanning object history.
3. If a caller wants to know prior provenance states, they must consult history.
4. History may explain how FLIP changed over time, but FLIP does not implement that behavior itself.

#### Development
This separation keeps FLIP useful and cheap. It also preserves the option to change history backend later without redefining what FLIP means.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-separation-1 | Current-State Only | Implemented | FLIP reads describe provenance for the current canonical values only. | `flip_map` is overwritten on each save; not a log |
| req-grid-flip-separation-2 | No History Replay Required | Implemented | TAP can answer FLIP queries without reconstructing provenance from object history. | `flip_map` is directly readable; no scan required |
| req-grid-flip-separation-3 | Historical Provenance Delegates To History | Implemented | Requests for provenance-over-time are explicitly served by history, not by FLIP itself. | History system is a separate deferred concern |

#### Future
If TAP later exposes "FLIP as of time X", that feature should be implemented as a composition of history and FLIP semantics rather than by expanding FLIP into its own historical ledger.

### Retirement Is A FLIP-Tracked State Change
----
RID: `req-grid-flip-retirement`

Status: `Implemented`

Retiring an object is the most consequential change its current state can undergo, so FLIP names the batch responsible for it the same way it names the batch behind every other tracked value.

#### Status Details
Implemented. The retirement path in `tap_grid/services/_impl.py` sets `Entity.deleted_at` with a bulk queryset update rather than a model save, so the save-time `update_flip_map()` hook never sees it. The retirement path therefore writes the entry itself, in the same transaction as the tombstone.

#### Implementation
1. When the service layer retires a node, its typed record's `flip_map` gains `deleted_at` mapped to the retiring batch id.
2. Every edge the retirement ends (by the endpoint rule or a contained cascade) records the same entry on its own typed record, pointing at the same batch.
3. The entry is written in the same transaction as the tombstone and is fail-closed: if it cannot be written, the retirement is not applied, matching the retirement event (`req-grid-service-delete-reason`).
4. `deleted_at` is a lifecycle field on the `Entity` spine, while `flip_map` lives on `BaseModel`. The key is the spine field's path. This is a deliberate, named exception to `req-grid-flip-default-3`: lifecycle timestamps are not stamped on ordinary writes, but the retirement of the object is recorded, because it is the change that ends the object's current state.
5. FLIP holds only the pointer. The reason, the cascade root and the actor stay in the retirement's batch event and the batch record (`req-grid-flip-batch`).
6. A repeat delete of an already-retired object is a silent no-op (`req-grid-service-delete-tombstone-6`) and does not rewrite the entry.
7. Types excluded from FLIP by `is_flip_enabled()` (internal-only, or no service-writeable fields) are not stamped.

#### Development
Without this, a current-state provenance read could name the batch behind every value on a retired object except the fact that it is retired. Exports and restores need the retiring batch as a direct read rather than a reconstruction from batch events.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-retirement-1 | Node Retirement Recorded | Implemented | After a plain `delete_node`, the retired node's `flip_map["deleted_at"]` is the retiring batch id. | |
| req-grid-flip-retirement-2 | Ended Edges Recorded | Implemented | Every edge ended by a retirement, plain or contained cascade, carries `flip_map["deleted_at"]` naming the retiring batch. | |
| req-grid-flip-retirement-3 | Cascade Nodes Recorded | Implemented | Every node retired by a contained cascade carries the entry. | |
| req-grid-flip-retirement-4 | Fail-Closed With The Tombstone | Implemented | If the entry cannot be written, or the retirement reaches it with no retiring batch, the retirement rolls back and the object stays live. | |
| req-grid-flip-retirement-5 | Repeat Delete Leaves It Alone | Implemented | A repeat delete of a retired object does not rewrite the entry. | |

### FLIP Moves Only On Change
----
RID: `req-grid-flip-change`

Status: `Implemented`

A FLIP entry names the batch that last **changed** the value at a field path, or first asserted it. A write that repeats what is already stored does not move the entry.

#### Status Details
Implemented for the service write pipeline and the GRIFT importer (Issue# 322 - tap). `tap_grid/write_classification.py` takes the snapshot, makes the comparison and yields the stamped set; `_execute_write_pipeline` in `tap_grid/services/_impl.py` takes the snapshot before it applies a payload, classifies after validation has cleaned the values to their stored types, and hands the stamped set to `BaseModel.save()` as `flip_changed_fields`. A create is unchanged: it stamps the fields its payload sent. Issue# 323 - tap holds the ruling; the design record is `docs/misc/doc-grid-batch-provenance-and-grift-patch-semantics.md`.

Before this, the touched set was taken from the shape of the payload: a patch stamped every field it named, a full replace the whole service-writeable surface, and a keep-absent replace every field the document sent, so a collector that re-sent an unchanged object re-pointed every sent field at the new batch.

Two things the comparison does that the rules below do not spell out. An integer and a float that are the same JSON number compare equal (`1` and `1.0`). First assertion applies only where FLIP is on for the type (`req-grid-flip-default`); an internal-only type has no entries to be missing.

#### Implementation
1. The write pipeline takes the object's stored values before it applies a payload and compares them, field by field, with the values after it. This one comparison is the source for FLIP, for the history decision (`req-grid-history-reobservation`) and for the spine pointers (`req-grid-entity-batch-pointers`).
2. A field whose value changed has its entry set to the writing batch.
3. A field the payload names, whose value did not change and which already has an entry, keeps its entry.
4. A field the payload names that has **no** entry yet is stamped even when the stored value does not move. This is the first assertion of the field. It is what turns a `null` nobody has looked at into a `null` a source asserted (`req-grid-node-observation`), so it counts as a change to what the grid knows.
5. A field the payload does not name is never stamped, whatever the verb. A field a full replace resets to its default is stamped only if the reset changed the stored value.
6. Comparison is by JSON value and is type-sensitive: `true` and `1` differ, `{}` and `{"k": null}` differ, object key order does not matter. Relations compare by id.
7. System-managed fields stay outside FLIP as `req-grid-flip-default-3` says, and are excluded from the comparison. The excluded list is kept in one place and a test fails when a system-managed field is added without it.
8. `req-grid-flip-default` rules 5 and 6 and `req-grid-service-write-keepabsent-6` state the same rule: touched and changed, or first asserted.
9. One writer is outside rule 2, and it is Proposed and not built: the adapter through which a migration applies a version step to stored rows (`req-grid-entity-model-version` rules 30 and 31 in `spec-grid-entity.md`). It changes values and stamps none of them. Each entry stays with the source that asserted the value, moved to a new field name where the step declares a rename. A write through the ordinary pipeline never takes this exception.

#### Development
The payload-shape rule was cheap and it made `flip_map` carry no more information than a single row-level batch stamp for collector-written data. Deriving the stamped set from a comparison is also what keeps the known-unknown distinction alive past the second write.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-change-1 | Repeat Leaves The Entry | Implemented | Writing an object again with identical values, by patch, replace, keep-absent replace or GRIFT import, leaves every `flip_map` entry pointing at the batch it pointed at before. | `tap_grid/tests/test_write_classification.py`: `test_repeat_leaves_every_entry`, `test_repeat_grift_import_leaves_every_entry` |
| req-grid-flip-change-2 | Change Moves One Entry | Implemented | A write that changes one field among several it sends moves that field's entry to the writing batch and no other. | `tap_grid/tests/test_write_classification.py`: `test_change_moves_one_entry` |
| req-grid-flip-change-3 | First Explicit Null Is Stamped | Implemented | A field created by omission has no entry; the first write that sends it as explicit `null` gives it one, although the stored value is still `null`. | `tap_grid/tests/test_write_classification.py`: `test_first_explicit_null_is_stamped` |
| req-grid-flip-change-4 | Repeat Explicit Null Is Not | Implemented | A second and third write sending the same explicit `null` leave that entry alone. | `tap_grid/tests/test_write_classification.py`: `test_repeat_explicit_null_is_not` |
| req-grid-flip-change-5 | Unnamed Field Never Stamped | Implemented | A replace that names one field leaves no entry on a field it did not name and whose value it did not change. | `tap_grid/tests/test_write_classification.py`: `test_unnamed_field_is_never_stamped` |
| req-grid-flip-change-6 | Type-Sensitive Comparison | Implemented | Replacing a stored JSON `true` with `1`, or `[false]` with `[0]`, is a change and moves the entry. | `tap_grid/tests/test_write_classification.py`: `test_type_sensitive_replace_is_a_change`, `test_values_compare_by_json_value_type_sensitively` |
