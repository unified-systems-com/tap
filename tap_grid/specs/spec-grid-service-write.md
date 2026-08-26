# Grid Service Write Specification

## Philosophy

Write operations are where the TAP service layer earns its keep. The write contract should let callers submit safe, schema-backed payloads without importing Django model classes, while guaranteeing that model validation, graph invariants, hotlinks, batching, and response shaping all happen consistently.

## Goals

|    |                  |                                                                                 |
| :---: | ---           | ---                                                                             |
| 1. | Consistent        | All node and edge writes use one shared enforcement pipeline                    |
| 2. | Schema-Driven     | Clients can submit JSON-safe write payloads described by published schemas      |
| 3. | Explicit          | Create, patch, and replace semantics are distinct and documented                |
| 4. | Batch-Backed      | Every write participates in batch semantics, including single-object writes     |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-service-write-surface | [Write Operation Surface](#write-operation-surface) | Implemented | Canonical public write verbs |
| req-grid-service-write-occ | [Optimistic Concurrency Parameter](#optimistic-concurrency-parameter) | Implemented | Mutating verbs accept `entity_expected_version` for atomic check-and-mutate |
| req-grid-service-write-payloads | [Write Payload Semantics](#write-payload-semantics) | Implemented | Slug-driven payload handling and strict rejection |
| req-grid-service-write-internal | [Internal-Only Write Exclusion](#internal-only-write-exclusion) | Implemented | Default service-layer CRUD verbs reject internal-only model types |
| req-grid-service-write-internal-create | [Trusted-Internal Create Entry Point](#trusted-internal-create-entry-point) | Proposed | `_create_node_internal` runs the full write pipeline minus the `INTERNAL_ONLY` gate for trusted subsystem helpers |
| req-grid-service-write-schema-cleanup | [Service Schema Simplification](#service-schema-simplification) | Implemented | Replace per-verb `SERVICE_CRUD_SCHEMA` with a simpler writable-field contract |
| req-grid-service-write-patch | [Patch And Replace Rules](#patch-and-replace-rules) | Implemented | Deep merge and immutable edge type rules |
| req-grid-service-write-observation | [Observation-Aware Writes](#observation-aware-writes) | Implemented | Explicit-null preservation + per-touched-field FLIP stamping; realizes the field-observation convention's write-path dependency |
| req-grid-service-write-validate | [Write Validation Stack](#write-validation-stack) | Implemented | full_clean, constraints, hotlinks |
| req-grid-service-write-results | [Write Result Envelopes](#write-result-envelopes) | Implemented | Minimal, standard, verbose |


### Write Operation Surface
----
RID: `req-grid-service-write-surface`
Status: `Implemented`

The service layer should publish explicit write verbs for common intents rather than hiding all writes behind one ambiguous mutation call.

#### Status Details
Current implementation exposes a small subset of these operations.

#### Implementation
Canonical write operations should include:

- `create_node(type_slug, payload, ...)`
- `patch_node(target, payload, ...)`
- `replace_node(target, payload, ...)`
- `delete_node(target, ...)`
- `create_edge(from_target, to_target, edge_type, payload, ...)`
- `patch_edge(target, payload, ...)`
- `replace_edge(target, payload, ...)`
- `delete_edge(target, ...)`
- `write_batch(operations, dry_run=False, ...)`

These public verbs should share one internal dispatcher/pipeline.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-surface-1 | Explicit Node Verbs | Implemented | The write contract defines create, patch, replace, and delete for nodes. | |
| req-grid-service-write-surface-2 | Explicit Edge Verbs | Implemented | The write contract defines create, patch, replace, and delete for edges. | |
| req-grid-service-write-surface-3 | Shared Internal Dispatcher | Implemented | Public write verbs execute through a common internal write pipeline. | |

#### Future
Decide whether any thin generic write wrapper is needed in addition to the explicit verbs.

### Optimistic Concurrency Parameter
----
RID: `req-grid-service-write-occ`
Status: `Implemented`

Every mutating write verb accepts an optional `entity_expected_version: int | None = None` parameter that engages optimistic concurrency control for that call. When set, the verb performs the version check atomically with the mutation; when omitted, the verb writes without a version check (existing behavior).

This is the per-verb surface of the OCC contract specified by `req-grid-service-batch-occ` in `spec-grid-service-batch.md`. The semantics, error code, and conflict-handling rules are defined there. This requirement only documents the verb signatures.

#### Implementation

Signatures gain `entity_expected_version`:

```python
def patch_node(
    target: str | uuid.UUID,
    payload: dict,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult: ...

def replace_node(
    target: str | uuid.UUID,
    payload: dict,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult: ...

def patch_edge(
    target: str | uuid.UUID,
    payload: dict,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult: ...

def replace_edge(
    target: str | uuid.UUID,
    payload: dict,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult: ...
```

Create verbs (`create_node`, `create_edge`) accept `entity_expected_version` only to provide a uniform call surface, but raise a stable error if it is set:

```python
def create_node(
    type_slug: str,
    payload: dict,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,  # must be None
    ...,
) -> WriteResult: ...
```

A create with `entity_expected_version` set is a caller mistake (no prior version exists to expect). The error code is `entity_expected_version_not_allowed_on_create`, distinct from `entity_version_conflict`, so callers see the right diagnostic.

For batched writes, the same parameter is carried on `WriteOperation.entity_expected_version` and threaded through the pipeline to the verb. Both surfaces — single-verb calls and `write_batch()` — share the implementation defined in `req-grid-service-batch-occ`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-occ-1 | Mutating Verbs Accept Expected Version | Approved for Development | `patch_node`, `replace_node`, `patch_edge`, `replace_edge` accept `entity_expected_version: int \| None = None`. | |
| req-grid-service-write-occ-2 | Create Verbs Reject Expected Version | Approved for Development | `create_node` and `create_edge` raise `entity_expected_version_not_allowed_on_create` if `entity_expected_version` is set. | Distinct from `entity_version_conflict`. |
| req-grid-service-write-occ-3 | Default Is Inline | Approved for Development | Omitting `entity_expected_version` runs the existing write path with no version check. | |
| req-grid-service-write-occ-4 | Conflict Surfaces As Standard Error | Approved for Development | A version mismatch returns the standard `WriteResult` with `errors[0].code == "entity_version_conflict"` and the detail payload described in `req-grid-service-batch-occ`. | |

### Service Schema Simplification
----
RID: `req-grid-service-write-schema-cleanup`
Status: `Implemented`

The per-model write surface is declared via four concise ClassVars on `BaseModel` subclasses. `SERVICE_CRUD_SCHEMA` is synthesized from these at class definition time and remains available for service-layer consumption and introspection.

#### Status Details
Implemented. The three-verb `SERVICE_CRUD_SCHEMA` dict is no longer written by hand on any concrete model. All 16 concrete subclasses across `tap_grid`, `plugins/lotr`, `tap_web`, and `tap_viz` now use the new contract.

#### Implementation
Concrete `BaseModel` subclasses declare:

1. `FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]]` — field name to JSON Schema fragment; the complete writable field surface.
2. `CREATE_REQUIRED: ClassVar[list[str]]` — fields required for `create_node`/`create_edge`. Defaults to `[]`.
3. `REPLACE_REQUIRED: ClassVar[list[str]]` — fields required for `replace_node`/`replace_edge`. Defaults to `CREATE_REQUIRED` if not declared.
4. `PATCH_EXTRA_FIELDS: ClassVar[dict[str, dict]]` — verb-specific fields patchable but absent from FIELD_CRUD_SCHEMA (e.g., lifecycle fields like `status`). Defaults to `{}`.

`BaseModel.__init_subclass__` calls `_check_service_contract()` to validate these at class definition time, then calls `_build_service_schemas()` to synthesize and assign `cls.SERVICE_CRUD_SCHEMA`. The service pipeline (`_execute_write_pipeline`) and `describe_node_type()` continue to read `SERVICE_CRUD_SCHEMA` unchanged.

#### Development
The cleanup resolved two mixed concerns that existed in the old design:

- **which fields** are writable (now declared in `FIELD_CRUD_SCHEMA`)
- **what each verb requires** (now declared in `CREATE_REQUIRED` / `REPLACE_REQUIRED`)

Patch semantics (all fields optional, extra lifecycle fields allowed) and replace semantics (reset-to-default for absent optional fields) remain in the service layer.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-schema-cleanup-1 | Simpler Writable Field Contract | Implemented | `FIELD_CRUD_SCHEMA` replaces the three-verb `SERVICE_CRUD_SCHEMA` as the per-model writable-field declaration. `SERVICE_CRUD_SCHEMA` is synthesized automatically. | |
| req-grid-service-write-schema-cleanup-2 | Sane Defaults On Create | Implemented | Models with no `CREATE_REQUIRED` (e.g., `Edge`, `Batch`, `LandingPage`) create instances with sane field defaults. | |
| req-grid-service-write-schema-cleanup-3 | Required-On-Create Supported | Implemented | `CREATE_REQUIRED` and `REPLACE_REQUIRED` provide explicit required-field control per verb. Previously deferred; now implemented as part of this cleanup. | |

### Internal-Only Write Exclusion
----
RID: `req-grid-service-write-internal`
Status: `Implemented`

The default service-layer CRUD surface must reject internal-only model types. These types are managed by dedicated subsystem services rather than ordinary generic create, patch, replace, and delete verbs.

#### Status Details
Implemented. `_execute_write_pipeline()` in `tap_grid/services.py` checks `getattr(model_cls, "INTERNAL_ONLY", False)` after resolving `model_cls` for all node verbs and raises `ServiceUnsupportedOperationError` with code `"unsupported_operation"` if the type is internal-only. `Batch` is the first internal-only type and is now rejected by `create_node`, `patch_node`, `replace_node`, and `delete_node`.

#### Implementation
The service-layer rule is:

1. Generic `create_node`, `patch_node`, `replace_node`, and `delete_node` reject internal-only model types.
2. Internal-only model types remain readable through normal read/search services unless another requirement limits that behavior.
3. Dedicated subsystem services may still create or mutate internal-only model types.
4. `Batch` is the first intended internal-only type and should not be writable through generic node CRUD verbs.

#### Development
This keeps public CRUD predictable while still letting TAP model internal graph-native artifacts as first-class entities.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-internal-1 | Generic Create Rejects Internal Only | Implemented | `create_node` rejects model types marked internal-only. | `ServiceUnsupportedOperationError` |
| req-grid-service-write-internal-2 | Generic Update Rejects Internal Only | Implemented | `patch_node` and `replace_node` reject internal-only model types. | Check after target entity resolution |
| req-grid-service-write-internal-3 | Generic Delete Rejects Internal Only | Implemented | `delete_node` rejects internal-only model types unless a future dedicated rule says otherwise. | |
| req-grid-service-write-internal-4 | Trusted-Internal Path Defined | Proposed | Internal-only types are written through `_create_node_internal` (see [Trusted-Internal Create Entry Point](#trusted-internal-create-entry-point)), which runs the full write pipeline minus the `INTERNAL_ONLY` gate. | Replaces the old "direct ORM" pattern for new internal-only types. `Batch`'s direct-ORM creation in `tap_grid/batch.py` may be migrated incidentally. |


### Trusted-Internal Create Entry Point
----
RID: `req-grid-service-write-internal-create`
Status: `Proposed`

INTERNAL_ONLY model types must still be created somewhere. Today the convention is "dedicated subsystem services use direct ORM" (`_ensure_batch` in `tap_grid/services.py` does this for `Batch`). That approach is fine for `Batch` because Batch is intentionally minimal — no `validate()` hooks, no `get_name()` projection, no provenance needed for the provenance row itself. It is not appropriate for richer INTERNAL_ONLY types like `Collector` and `CollectionJob`, which have `FIELD_VALIDATION_SCHEMA`, `validate()` hooks, `get_name()` projections, version semantics, and benefit from provenance and FLIP.

Direct ORM for every internal helper means each helper re-implements pipeline features inconsistently. The fix is one private entry point that runs the same pipeline as `create_node` minus the `INTERNAL_ONLY` gate.

#### Implementation

A new private function in `tap_grid/services.py`:

```python
def _create_node_internal(
    type_slug: str,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_id: uuid.UUID | None = None,
    dimensions: dict[str, str] | None = None,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Trusted-internal create for INTERNAL_ONLY types.

    Runs the full write pipeline — validation, full_clean, name sync from
    get_name(), version increment, history record, provenance, FLIP stamp —
    minus the INTERNAL_ONLY gate. Callers are limited by convention to
    subsystem registration helpers (e.g. `register_collector`'s
    `_ensure_collector_node`); the leading underscore signals the
    boundary.
    """
```

Properties:

- **Leading underscore.** Not re-exported from `tap_grid.services` or `tap_grid.__init__`. Importable only via the private path; the underscore is the discipline tripwire.
- **Pipeline parity.** Runs every step `create_node` runs (input normalization, schema validation, model `full_clean`, graph constraints, hotlinks, persistence, provenance, FLIP) except the `INTERNAL_ONLY` gate at `_execute_write_pipeline` step 3.
- **Greppable callers.** Every legitimate use is locatable in one repo search. New uses are visible in code review.
- **Deterministic entity_id support.** Accepts an optional `entity_id` (UUIDv5-derived in the dual-existence pattern) so registration helpers can produce stable cross-grid identity.
- **Honest threat model.** This is a tripwire for accidental misuse, not a wall against in-process malicious code. In Python, anything in-process can call private functions. The real security boundary lives at the network ingress layer (`tap_api`, panel POST handlers); INTERNAL_ONLY + leading underscore are sufficient inside the process.

#### Test escape hatch

Tests legitimately need to create INTERNAL_ONLY entities for assertions about model behavior, dimension defaults, validation, and registration semantics. A separate DEBUG-gated entry point provides the test bypass without polluting production policy:

```python
def _create_node_internal_for_test(...) -> WriteResult:
    """Same as _create_node_internal, intended for tests only.

    Raises RuntimeError if called outside DEBUG / test settings.
    """
```

The DEBUG gate keeps the test bypass out of production code paths; the explicit naming keeps test invocations visible and auditable.

#### Migration

- New INTERNAL_ONLY types (`Collector`, `CollectionJob`, future `Emitter`, `Action`, etc.) use `_create_node_internal` from day one.
- `Batch`'s existing `_ensure_batch` continues to use direct ORM; migrating it to `_create_node_internal` is an incidental improvement that should be considered when the surrounding code is next touched, but is not blocking.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-internal-create-1 | Private Entry Point Exists | Proposed | `_create_node_internal` is defined in `tap_grid/services.py` and is not re-exported from public modules. | |
| req-grid-service-write-internal-create-2 | Full Pipeline Minus Gate | Proposed | The function runs every step of the existing `_execute_write_pipeline` for `create_node` verbs except the `INTERNAL_ONLY` check at services.py:267. | |
| req-grid-service-write-internal-create-3 | Deterministic Entity ID Accepted | Proposed | The function accepts an optional `entity_id` argument and uses it for the created Entity row when provided. | Required for dual-existence registration helpers. |
| req-grid-service-write-internal-create-4 | Convention-Based Caller Discipline | Proposed | The leading underscore and module location are the only enforcement; the spec acknowledges this is a tripwire, not a wall against in-process misuse. | |
| req-grid-service-write-internal-create-5 | DEBUG-Gated Test Bypass | Proposed | A separate `_create_node_internal_for_test` entry point provides the same semantics for tests; raises `RuntimeError` if called outside DEBUG / test settings. | |
| req-grid-service-write-internal-create-6 | History And Provenance Preserved | Proposed | INTERNAL_ONLY creates through `_create_node_internal` record `BatchEvent` provenance and `HistoricalRecord` rows the same way ordinary creates do. | |


### Write Payload Semantics
----
RID: `req-grid-service-write-payloads`
Status: `Implemented`

Public write payloads should be schema-backed, type-aware, and strict.

#### Status Details
This is a new contract requirement intended to eliminate client-side ad hoc JSON-to-model translation.

#### Implementation
Node creation is slug-driven:

- caller provides a node type slug
- caller provides a payload shaped by the published create schema
- service layer resolves slug to model class through the registry
- service layer instantiates and validates the model consistently

Patch and replace writes operate on a target plus a payload described by the corresponding published schemas.

Unknown fields are rejected. Omitted fields remain unchanged unless the chosen operation semantics require full replacement. Explicit nulls clear values only where allowed by schema/model constraints.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-payloads-1 | Slug Driven Node Writes | Implemented | Public node creation uses type slugs plus payloads rather than model-class imports. | |
| req-grid-service-write-payloads-2 | Strict Field Rejection | Implemented | Unknown fields in write payloads are rejected rather than ignored. | |
| req-grid-service-write-payloads-3 | Omitted Fields Preserved On Patch | Implemented | Patch semantics leave omitted fields unchanged unless explicitly nulled where allowed. | |

#### Future
Consider support for additional mutation semantics such as underwrite once concrete use cases emerge.


### Patch And Replace Rules
----
RID: `req-grid-service-write-patch`
Status: `Implemented`

Patch and replace are distinct operations and must not be conflated.

#### Status Details
This requirement captures the current contract decisions for structured payload handling.

#### Implementation
Patch semantics:

- omitted fields remain unchanged
- explicit nulls clear values only where schema/model rules allow
- nested JSON payloads use deep merge semantics

Replace semantics:

- caller replaces the addressed payload according to the operation schema
- for edges, replace means replacing edge payload/properties only
- edge type is immutable and may never be changed by replace

`flip_map` is not user-writable and should not be exposed as a client-writeable payload field.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-patch-1 | JSONField Deep Merge, Scalars Replace | Implemented | Patch operations apply deep merge semantics to JSONField values. Scalar fields (CharField, IntegerField, etc.) always replace on patch. | |
| req-grid-service-write-patch-2 | Edge Replace Does Not Change Type | Implemented | Replace operations for edges do not allow `edge_type` changes. | |
| req-grid-service-write-patch-3 | Internal Flip Map Not User Writable | Implemented | `flip_map` is not part of the user-writeable payload contract. | |
| req-grid-service-write-patch-4 | Replace Node Covers User-Writable Model Fields | Implemented | `replace_node` replaces all user-writable fields on the `BaseModel`-derived class. Fields on the Entity spine (id, entity_type, originating_grid_id, created_at) are not part of the replace payload. | |


### Observation-Aware Writes
----
RID: `req-grid-service-write-observation`
Status: `Implemented`

The write pipeline must honor the grid field-observation convention (`spec-grid-node.md` `req-grid-node-observation`): an explicit `null` is a *deliberate assertion of absence* that clears a field and earns provenance, distinct from an *omitted* field that is left untouched; and FLIP stamps only the fields a write actually touched. This requirement realizes the write-path dependency the convention named, and closes two spec-vs-code gaps where the behavior was already specified but not implemented: `req-grid-service-write-patch` ("explicit nulls clear values only where schema/model rules allow"; "omitted fields remain unchanged") and `req-grid-flip-default` (`req-grid-flip-default-4`: "changed_fields controls partial vs full stamping").

#### Status Details
Before this requirement, `_execute_write_pipeline` stripped every `None` from the payload (`{k: v for k, v in payload if v is not None}`) — so an explicit null could neither clear a field nor stamp FLIP — and saved without scoping FLIP to touched fields, so FLIP stamped the *full* service-writeable surface on every write. Both `req-grid-service-write-patch` and `req-grid-flip-default-4` were marked Implemented while describing behavior the code did not perform.

#### Implementation
**1. Explicit-null preservation (the inbound write-intent boundary).** Payload preparation preserves an explicit `null` for a field whose verb schema permits null (`type` includes `"null"`). A `null` on a field that does *not* permit null is dropped (treated as field-absent), preserving today's lenient behavior; a future tightening may reject it instead. The three inbound intents then resolve:

| Inbound intent | Action |
| --- | --- |
| Field **absent** from payload | Untouched: not applied, not FLIP-stamped. |
| Field present, **explicit `null`** (null permitted) | Set to `null`; FLIP-stamped (deliberate absence → known unknown). |
| Field present with a value or `""` | Set; FLIP-stamped. |

The JSON `absent`-vs-`null` distinction is preserved by Python dict semantics (missing key vs key with `None`); the pipeline must not flatten it.

**2. JSON null clears, it does not merge.** In a patch, an explicit `null` for a `JSONField` sets the field to `null` (clear). Deep-merge applies only to a present object value (`req-grid-service-write-patch-1`); merging `None` is never attempted.

**3. FLIP stamps only touched fields.** FLIP stamping is scoped to the fields a write touched, decoupled from Django's `update_fields` (which cannot drive create-time scope because an INSERT writes all columns):

| Verb | FLIP-touched set |
| --- | --- |
| `create_node` / `create_edge` | the fields present in the payload (explicitly provided, including explicit nulls) |
| `patch_node` / `patch_edge` | the fields present in the payload |
| `replace_node` / `replace_edge` | the full replace surface (replace asserts the complete object) |

A field omitted from a create or patch is left out of FLIP — no entry — so it reads as an *unknown unknown* (nobody asserted it) per the convention. The signal is carried to `BaseModel.save()` as an explicit `flip_changed_fields` argument; when absent (non-pipeline saves), the existing `update_fields`-derived behavior is unchanged.

**4. Create-time semantics.** A create stamps FLIP only for fields the caller provided. Fields that fall to their model default (omitted) receive no FLIP entry. A defaulted `""` is therefore not provenance-bearing — it is a default, not an observation — consistent with "omitted leaves FLIP alone."

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-observation-1 | Explicit Null Preserved Where Permitted | Implemented | An explicit `null` is preserved through validation and application for a field whose verb schema permits null; it clears the field. | Realizes `req-grid-service-write-patch` explicit-null clause. |
| req-grid-service-write-observation-2 | Null On Non-Null Field Dropped | Implemented | A `null` on a field that does not permit null is dropped (treated as absent), not a hard error. | Backward-compatible; future tightening may reject. |
| req-grid-service-write-observation-3 | Absent Field Untouched | Implemented | A field omitted from a patch/create payload is neither applied nor FLIP-stamped. | `absent ≠ null`. |
| req-grid-service-write-observation-4 | JSON Null Clears | Implemented | An explicit `null` for a JSONField clears it; deep-merge is attempted only on a present object value. | |
| req-grid-service-write-observation-5 | FLIP Scoped To Touched Fields | Implemented | FLIP stamps only payload-present fields for create/patch and the full replace surface for replace; omitted fields get no entry. | Realizes `req-grid-flip-default-4`; via `flip_changed_fields`. |
| req-grid-service-write-observation-6 | Create Stamps Only Provided Fields | Implemented | A create stamps FLIP only for provided fields; defaulted/omitted fields receive no FLIP entry. | Defaulted `""` is not provenance-bearing. |

#### Future
- **Reject null on non-null fields.** Tighten `req-grid-service-write-observation-2` from drop to a structured validation error once callers/import paths are confirmed not to rely on the lenient drop.
- **Not-applicable flavor (Phase 2).** When the convention's Phase 2 lands, an inbound *not-applicable* assertion (`x-tap-absence.not_applicable.permitted`) stores `null` and records the flavor via extended FLIP — built on the explicit-null boundary defined here. See `req-grid-node-observation-8`.


### Write Validation Stack
----
RID: `req-grid-service-write-validate`
Status: `Implemented`

All writes should pass through the same ordered validation stack before persistence.

#### Status Details
Current behavior is split across model methods, helper functions, and surrounding code. This requirement centralizes the intended order.

#### Implementation
Write validation should include:

1. input normalization
2. security/authz hook stub
3. target resolution and object loading
4. schema validation
5. strict field rejection
6. model `full_clean()`
7. service-layer graph constraint checks
8. hotlink validation
9. transaction and batch setup
10. persistence
11. provenance/batch recording
12. response shaping

Model validation is the deepest invariant layer for object shape and field semantics. The service layer orchestrates cross-object and graph-level invariants above that.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-validate-1 | Full Clean Always Runs | Implemented | All write operations call `full_clean()` before persistence. | |
| req-grid-service-write-validate-2 | Constraint Checks Explicit | Implemented | The write pipeline includes service-layer graph constraint validation. | |
| req-grid-service-write-validate-3 | Hotlink Checks Explicit | Implemented | The write pipeline includes explicit hotlink validation. | |
| req-grid-service-write-validate-4 | Security Hook Reserved | Implemented | The write pipeline reserves a defined position for future authorization enforcement. | |

#### Future
Document which invariants belong in models versus the service layer once implementation work shakes out edge cases.


### Write Result Envelopes
----
RID: `req-grid-service-write-results`
Status: `Implemented`

Write results should be structured, machine-usable, and flexible enough for lightweight callers and deep admin/bot inspection.

#### Status Details
This requirement defines result envelopes rather than raw booleans or inconsistent per-call outputs.

#### Implementation
Write responses should support:

- minimal
- standard
- verbose

Minimal should include success confirmation, object identity, and batch identity.

Standard should add object summary and warnings.

Verbose should add enough structured context for admins and bots to dig deeper into backend details without exposing raw Django/ORM internals directly to ordinary callers.

Write result envelopes should identify the relevant schema refs and may optionally inline schemas.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-write-results-1 | Structured Result Envelope | Implemented | Write operations return structured envelopes rather than ad hoc raw values alone. | |
| req-grid-service-write-results-2 | Detail Modes Defined | Implemented | The write contract defines minimal, standard, and verbose result modes. | |
| req-grid-service-write-results-3 | Verbose Supports Deep Inspection | Implemented | Verbose mode includes sufficient non-sensitive references and diagnostics for admin or bot follow-up. | |

#### Future
Define exact field-level contents of each result mode once the error and batch contracts are implemented.


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
