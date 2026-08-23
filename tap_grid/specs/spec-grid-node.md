# Grid Node Specification

## Philosophy

Nodes are the typed participants of the grid. Each node type is a concrete `BaseModel` subclass that pairs a type-specific table with a row on the entity spine. The `BaseModel` pattern provides the machinery that makes a plain Django model a first-class graph citizen — spine attachment, type registration, constraint declaration, and dimension defaults — without requiring plugin authors to know the internals.

## Goals

|    |               |                                                                                                  |
| :---: | ---        | ---                                                                                              |
| 1. | Typed         | Nodes declare a type slug (`ENTITY_TYPE`) that identifies their role in the graph               |
| 2. | Extensible    | Adding a new node type requires only a `BaseModel` subclass; no framework changes are needed    |
| 3. | First-Class   | Nodes are entities: each node instance has a backing `Entity` row on the spine                  |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-node-model | [Node Model Declaration](#node-model-declaration) | Implemented | `BaseModel` provides the abstract pattern all node types inherit |
| req-grid-node-display | [Node Display Name](#node-display-name) | Implemented | `get_display_name()` produces the label stored on the backing Entity at creation time |
| req-grid-node-service | [Node Service Layer](#node-service-layer) | Implemented | `create_entity()`, `update_entity()`, and `delete_entity()` as the canonical Entity-level service API |
| req-grid-node-constraints | [Node Constraint Declaration](#node-constraint-declaration) | Implemented | `OUTBOUND_EDGES` / `INBOUND_EDGES` declared on node types; registered at class-definition time |
| req-grid-node-observation | [Field Observation Semantics](#field-observation-semantics) | Approved for Development | `null` = unobserved, concrete-empty = observed-empty, declared per-field via `x-tap-absence`; FLIP distinguishes known vs unknown unknown. Phase 2 (Codd's not-applicable, via extended FLIP) reserved |


## Explanation

Nodes in the grid are typed objects. Concretely, a node is any instance of a concrete `BaseModel` subclass — `Concept`, `Precept`, `Dimension`, `Character`, etc. The `BaseModel` pattern ensures:

1. Every node instance has a corresponding `Entity` row on the spine (the canonical reference).
2. Every node type declares an `ENTITY_TYPE` slug, registered in the model registry at class-definition time.
3. Node creation is atomic with Entity creation — no partial state enters the graph.
4. Edge constraints are declared on the node type and enforced at the service layer when edges are created.

Nodes are distinct from edges (which model relationships between nodes) and from `Entity` (the spine record that backs them). The entity spec (`spec-grid-entity.md`) covers Entity-centric concerns: spine structure, type declaration, auto-creation machinery, and resolution. This spec covers node-centric concerns: the `BaseModel` pattern itself, how a new node type is declared, the display name convention, and the service API for node instances.


### Node Model Declaration
----
RID: `req-grid-node-model`
Status: `Implemented`

`BaseModel` is the abstract Django model that every node type inherits from. It provides the common fields, the spine attachment machinery, and the class-definition hooks that register the type in the model registry and constraint system.

#### Status Details
Implemented in `tap_grid/models.py` as `class BaseModel(models.Model)`. Retroactively specified here.

#### Implementation
**Fields inherited by every node type:**

| Field | Type | Notes |
| --- | --- | --- |
| `entity` | OneToOneField → Entity, CASCADE | The backing spine record. Auto-created on first save if not set. |
| `batch_id` | CharField(36, db_index=True) | UUIDv7 of the FLIP batch this change was part of (Phase 2). |

`originating_grid_id`, `created_at`, and `updated_at` live on `Entity` — the authoritative source of record. `BaseModel.save()` touches `entity.updated_at` on every typed-model save so the Entity timestamp stays current.

`BaseModel.Meta` sets `abstract = True` — no `tap_basemodel` table is created.

**`__init_subclass__` hooks** (fire at class-definition time, before any request):

| Hook | Effect |
| --- | --- |
| Model registry | If the subclass declares `ENTITY_TYPE` in its own `__dict__`, calls `register_entity_type()` in `tap_grid/registry.py`. Abstract subclasses that omit `ENTITY_TYPE` are skipped. |
| Constraint registration | If the subclass declares `OUTBOUND_EDGES` or `INBOUND_EDGES`, calls `register_constraints()` in `tap_grid/constraints.py`. |
| FLIP config | Calls `get_model_flip_config()` to cache the subclass's FLIP configuration at class-definition time. |
| Table-classification guard | Rejects any `GRID_TABLE_ROLE` declaration in the subclass body with `ImproperlyConfigured` — grid-table classification is inherited from `BaseModel` (`"domain"`), never declared by a subclass; spine is core-only. See `req-grid-table-classification.sec` (spec-grid-security.md). |

**Grid table classification (`GRID_TABLE_ROLE`)** — `BaseModel` carries `GRID_TABLE_ROLE =
"domain"`, inherited by every concrete subclass: being a BaseModel IS being a grid domain
table, and the security consumers (ORM read backstop, search-role DB grant) derive their
table sets from this classification. A subclass — core or plugin — MUST NOT declare
`GRID_TABLE_ROLE` in its own body; the `__init_subclass__` guard fails the class at import.
The full contract, including the core-only `"spine"` value and the fail-closed derivation
rules, is owned by `req-grid-table-classification.sec` in `spec-grid-security.md`.

A minimal concrete node type declaration:

```python
class Concept(BaseModel):
    ENTITY_TYPE: ClassVar[str] = "concept"
    summary = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "core_examples_concept"
```

Creating an instance auto-creates the backing Entity:

```python
concept = Concept.objects.create(summary="Separation of Concerns")
# concept.entity is now a persisted Entity row with entity_type="concept"
```

#### Development

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-node-model-1 | BaseModel Is Abstract | Implemented | `BaseModel` sets `Meta.abstract = True`; no `tap_basemodel` table exists in the schema. | |
| req-grid-node-model-2 | Common Fields Present | Implemented | Every concrete `BaseModel` subclass inherits `entity` and `batch_id`. Timestamps and grid ID live on the backing Entity. | |
| req-grid-node-model-3 | Registry Hook | Implemented | `__init_subclass__` registers the subclass in `_ENTITY_MODEL_REGISTRY` when `ENTITY_TYPE` is declared in the subclass's own `__dict__`. Abstract subclasses that omit `ENTITY_TYPE` are not registered. | |
| req-grid-node-model-4 | Constraint Hook | Implemented | `__init_subclass__` calls `register_constraints()` when `OUTBOUND_EDGES` or `INBOUND_EDGES` is present on the subclass. | |
| req-grid-node-model-5 | FLIP Hook | Implemented | `__init_subclass__` calls `get_model_flip_config()` to cache FLIP config for the subclass at class-definition time. | |

#### Future
Consider a Django system check that validates all registered `ENTITY_TYPE` values against the `EntityType` table at startup to surface misconfigured plugins early or a more clever way to automagically assign names that won't risk namespace pollution.  
Consider revisiting whether `batch_id` should move to `Entity` or be handled differently once FLIP matures — the tight entity-node coupling may change how FLIP tracks provenance.


### Node Display Name
----
RID: `req-grid-node-display`
Status: `Implemented`

`BaseModel` is the source of truth for a node's display name; `Entity.name` is a subordinate materialized projection that the framework keeps current on every model save. The projection exists because spine-level queries (search, gryphon, badge counts, edge envelopes) need a name that's reachable without resolving the typed model — but the value is always derived from the typed model, never authored directly on the spine.

#### Source-Of-Truth Contract

- The typed `BaseModel` subclass owns the name. The canonical accessor is `BaseModel.get_name()`, which subclasses override to project from whichever field(s) make sense (typically `self.name`).
- `Entity.name` is a materialized projection of `get_name()` for cross-type query efficiency. It is read by anything that walks the spine; it is **not** a separate authority.
- Outside of (a) the create path, (b) the per-save sync described below, and (c) the GRIFT importer's envelope-driven spine sync (see [spec-grid-import-grift.md](spec-grid-import-grift.md) `req-grid-import-grift-batch` "Spine Sync For Replaced Entities"), nothing should write to `Entity.name`. Direct writes will be silently overwritten on the next `BaseModel.save()`.

This is a deliberate sub-service-layer construct: the service layer (`patch_node`, `replace_node`, `create_node`) keeps its "model fields only" contract, and the spine projection follows automatically from the model write. Callers do not need to remember to call a `sync_display_name()` helper, and there is no escape hatch by which model and spine can diverge through normal save paths.

#### Implementation
`BaseModel` defines:

```python
def get_name(self) -> str:
    """Return the name for the auto-created Entity.

    Defaults to empty string. Subclasses may override to project a
    meaningful label without requiring callers to set it explicitly.
    The returned value is stored as Entity.name (a materialized projection
    for cross-type query efficiency).
    """
    return ""
```

`BaseModel.save()` writes the projection on **both** code paths:

1. **Create path** — when `entity_id` is None, `Entity.objects.create(name=self.get_name(), ...)` materializes the spine projection alongside the auto-created Entity row.
2. **Update path** — when `entity_id` is already set, after `super().save(...)` returns, the same `.update()` call that bumps `Entity.updated_at` and `Entity.version` also re-materializes `name` whenever `self.entity.name != self.get_name()`. The projection cannot drift past a single save.

The default `get_name()` returns an empty string. Subclasses override it to produce a meaningful label from their own fields:

```python
class Concept(BaseModel):
    def get_name(self) -> str:
        return self.summary[:80] if self.summary else ""
```

`Edge` overrides `get_name()` to produce a structural label: `"{from_entity_id} --[{edge_type}]--> {to_entity_id}"`.

#### History And Signal Behavior

The per-save spine sync uses `Entity.objects.filter(pk=self.entity_id).update(**spine_updates)` — a Django ORM `.update()` query, **not** `entity.save()`. This has two relevant properties for the history subsystem:

- `Entity` is `models.Model` (not `BaseModel`) and has no `HistoricalRecords` declaration. There is no per-Entity history table, so there is no Entity-side history record to write under any code path.
- Even hypothetically, `.update()` bypasses Django pre/post-save signals entirely, so a `simple_history` `post_save` hook would not fire. Belt-and-suspenders.

Net effect: every `BaseModel.save()` writes exactly one history row (on the typed model's history table, via `simple_history`'s `post_save` on the model itself) and zero on the spine. The spine sync is a pure projection refresh and is invisible to history consumers.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-node-display-1 | Default Returns Empty String | Implemented | `BaseModel.get_name()` returns `""` by default. | |
| req-grid-node-display-2 | Stored On Create | Implemented | `BaseModel.save()` passes `get_name()` to `Entity.objects.create()` on the create path. | |
| req-grid-node-display-3 | Subclass Override | Implemented | Subclasses may override `get_name()` to project a meaningful label without requiring callers to set it. | `Edge`, `Finding`, `Concept`, etc. |
| req-grid-node-display-4 | Synced On Save | Implemented | `BaseModel.save()` re-materializes `Entity.name` from `get_name()` whenever it has drifted. Folded into the existing `updated_at`/`version` `.update()`; no extra round trip. | Drift can only persist for the duration of one save. |
| req-grid-node-display-5 | No Entity History Side-Effect | Implemented | The spine sync is a `.update()` query that bypasses signals, and `Entity` has no `HistoricalRecords`. No history row is written for the Entity row when the projection refreshes. | History rows continue to be written on the typed model's history table (one per save). |
| req-grid-node-display-6 | Source-Of-Truth Direction | Implemented | `BaseModel` writes flow into `Entity.name`; the reverse direction is not supported by normal write paths and direct writes to `Entity.name` are overwritten on the next model save. | The GRIFT importer's spine-sync post-pass is the documented exception, scoped to envelope-declared values during import. |


### Node Service Layer
----
RID: `req-grid-node-service`
Status: `Implemented`

`tap_grid/services.py` provides the canonical service-layer API for Entity-level node operations. Application code that creates, updates, or deletes entity spine records should use these functions rather than direct ORM calls, so that FLIP can be wired in at these call sites without changing callers.

#### Status Details
Implemented in `tap_grid/services.py`. Retroactively specified here.

#### Implementation
**`create_entity(entity_type, display_name="", **kwargs) -> Entity`**:
Creates a bare Entity record directly on the spine. Intended for cases where a typed domain model does not exist or is not needed — e.g., tests that need an entity as an edge endpoint, or raw entity creation where the type has no domain model. For typed node creation, `ModelClass.objects.create(...)` is the standard path; `BaseModel.save()` auto-creates the backing Entity atomically.

**`update_entity(entity, **kwargs) -> Entity`**:
Updates the named fields on an Entity instance and calls `save(update_fields=[...])`. Avoids clobbering unspecified fields. Returns the updated Entity.

**`delete_entity(entity) -> None`**:
Deletes the Entity row. Cascades to the typed domain model row via the `OneToOneField` and to all `Edge` rows that reference this Entity as `from_entity` or `to_entity`.

#### Development

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-node-service-1 | create_entity Creates Spine Record | Implemented | `create_entity()` creates and returns an `Entity` with the given `entity_type` and optional `display_name`. | |
| req-grid-node-service-2 | update_entity Uses update_fields | Implemented | `update_entity()` calls `entity.save(update_fields=[...] + ["updated_at"])` to avoid clobbering unrelated fields. | |
| req-grid-node-service-3 | delete_entity Cascades | Implemented | `delete_entity()` deletes the Entity; the DB cascade removes the domain model row and all referencing edges. | |

#### Future
Once FLIP is active, `create_entity()`, `update_entity()`, and `delete_entity()` should record provenance events. The integration points are already identified; no call-site changes will be needed.
Consider whether typed node creation should route through a `create_node(model_cls, **kwargs)` service function to enforce FLIP recording uniformly across both the bare-entity and typed-model creation paths.


### Node Constraint Declaration
----
RID: `req-grid-node-constraints`
Status: `Implemented`

Node types declare their edge participation rules via `OUTBOUND_EDGES` and `INBOUND_EDGES` class variables. These declarations are registered at class-definition time and consumed by the edge constraint validation system. The full validation semantics — Permission Union, explicit blocks, and edge-type constraints — live in `spec-grid-edge.md` under `req-grid-edge-constraints`.

#### Status Details
Implemented in `tap_grid/models.py` (`BaseModel.__init_subclass__`) and `tap_grid/constraints.py` (`register_constraints()`). Retroactively specified here.

#### Implementation
Node types optionally declare:

```python
class Concept(BaseModel):
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "concept"}, {"type": "precept"}],
            "edges": [{"type": "APPLIES_TO"}],
        },
        {
            "nodes": [{"type": "concept"}],
            "edges": [{"type": "DEPENDS_ON"}],
        },
    ]
    INBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "concept"}],
            "edges": [{"type": "APPLIES_TO"}, {"type": "DEPENDS_ON"}],
        },
    ]
```

Declaration rules:

| Declaration | Meaning |
| --- | --- |
| Entry with `"nodes"` key | This edge type may connect to/from only the listed node types |
| Entry without `"nodes"` key | Wildcard — this edge type may connect to/from any node type |
| `OUTBOUND_EDGES = []` | Explicit block-all — this node cannot create any outbound edges |
| `INBOUND_EDGES = []` | Explicit block-all — this node cannot receive any inbound edges |
| Attribute omitted entirely | Unconstrained — the node has not expressed a preference; edge-type constraints still apply |

`BaseModel.__init_subclass__` calls `register_constraints(entity_type, outbound, inbound)` which parses the declaration and stores it in `_NODE_REGISTRY` in `tap_grid/constraints.py`.

#### Development

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-node-constraints-1 | OUTBOUND_EDGES Registered | Implemented | When a subclass declares `OUTBOUND_EDGES`, `__init_subclass__` calls `register_constraints()` to store the parsed outbound rules in `_NODE_REGISTRY`. | |
| req-grid-node-constraints-2 | INBOUND_EDGES Registered | Implemented | When a subclass declares `INBOUND_EDGES`, `__init_subclass__` calls `register_constraints()` to store the parsed inbound rules in `_NODE_REGISTRY`. | |
| req-grid-node-constraints-3 | Empty List Is Explicit Block | Implemented | `OUTBOUND_EDGES = []` or `INBOUND_EDGES = []` registers a block-all that cannot be overridden by edge-type constraints. | |
| req-grid-node-constraints-4 | Omitted Attribute Is Unconstrained | Implemented | A node type that omits `OUTBOUND_EDGES` or `INBOUND_EDGES` has no registered constraint for that direction; the constraint system treats it as unconstrained. | |
| req-grid-node-constraints-5 | Wildcard Via Omitting Nodes Key | Implemented | Omitting `"nodes"` from an entry in `OUTBOUND_EDGES` or `INBOUND_EDGES` results in a wildcard — any node type is allowed for those edge types in that direction. | |

#### Future
Consider a management command that audits registered node constraints against the entity type registry to detect mismatched type slugs in constraint declarations at startup.


### Field Observation Semantics
----
RID: `req-grid-node-observation`
Status: `Approved for Development`

TAP is an observation graph: a node's field value records *what a source observed*, not merely *what is true*. The difference between "we never observed this," "we observed it to be empty," and "this can't apply here" is first-class information, not an implementation accident — and it must be **declared on the field**, discoverable by external readers, writers, the API, and the Gryphon traversal layer, rather than buried in a code comment that only a human reading the source can see.

This requirement is staged:

- **Phase 1 (this requirement, Approved for Development).** The stored-value taxonomy (`null` = unobserved, concrete-empty = observed-empty, value = observed), the known-vs-unknown-unknown distinction via FLIP, the declarative `x-tap-absence` field annotation, and the inbound write-intent boundary.
- **Phase 2 (reserved, deferred — see Future).** Codd's *not-applicable* third state, represented out-of-band by **extending FLIP** so provenance covers applicability rather than standing up a parallel mechanism. Declared in `x-tap-absence` now; not consumed yet.

Phase 1 introduces no new *storage* — the substrate (nullable columns, the FLIP map, the field schema) already exists. Both halves are now realized: the static half (the stored-value taxonomy) in the column, and the dynamic half (explicit-null clears a field and stamps FLIP; an omitted field touches neither) in the write pipeline via `spec-grid-service-write.md` `req-grid-service-write-observation`.

#### The Three States (Phase 1)

For a column-backed field, the stored value carries observational meaning:

| Stored value | Meaning | Example |
| --- | --- | --- |
| `null` | **Unobserved** — unknown, not-yet-seen, or not-applicable. No source has asserted a value. | A scanner sees a `network_interface` by name but never captures its hardware address → `mac_address = null`. |
| `""` (or `[]`, `{}`) | **Observed-empty** — a source looked and the value is genuinely empty. | A source confirms an interface has no description → `description = ""`. |
| a value | **Observed value** — a source captured a concrete value. | The MAC was captured → `mac_address = "00:11:22:33:44:55"`. |

Observed-empty is a **container-type** state, not a universal one. Container-like fields — strings (`""`), lists (`[]`), maps (`{}`) — carry three states (`null` / empty / value); **scalar** fields (integer, float, boolean, datetime, UUID, FK) have *no empty form* and carry two (`null` / value). Inventing an empty for a scalar — "empty int = 0", "empty bool = false" — is exactly the "null island" failure mode the convention forbids: an unobserved value is `null`, never a sentinel like `0`, `0.0`, `(0,0)`, `9999-12-31`, or `"unknown"`. The per-field `x-tap-absence.empty_is_meaningful` flag is the discriminator — it declares whether a field even *has* an observed-empty state, so consumers (and the future Gryphon `IS EMPTY` predicate) know whether to test for it. (Note: a collection's empty state is self-reporting *only when it is a column*; an empty *edge set* — zero edges of a type — is not self-reporting and is handled by dimensions/perspectives, not this convention.)

Phase 1 reads `null` as **unobserved**. It does *not* try to express Codd's *not-applicable* in the column — that distinction is deferred to Phase 2 and represented out-of-band (below), never by a second column value or an in-band sentinel. We do not adopt Codd's two-mark four-valued logic; we keep one `NULL` and recover the lost axes (responsibility now, applicability in Phase 2) through FLIP. **No shadow columns.**

#### Declared Absence Semantics (`x-tap-absence`)

The meaning of a field's absence is **declared in the field's `FIELD_CRUD_SCHEMA` entry**, not in a code comment. Because `_build_service_schemas` copies each field's schema dict wholesale into the published `SERVICE_CRUD_SCHEMA` (create/patch/replace), the annotation is automatically available to every consumer of the registry-backed schema surface — external readers and writers, the API, and schema-driven tooling — with no extra plumbing. It is a non-validating *annotation* keyword (JSON Schema treats unknown keywords as annotations, not assertions; the `x-` prefix follows the OpenAPI extension convention), so stock validators pass it through untouched while semantic consumers read it. (Publication makes the semantics *discoverable*; acting on them in queries — Gryphon's `IS UNOBSERVED`-style predicates — is a separate, Future concern.)

```jsonc
"mac_address": {
  "type": ["string", "null"],
  "x-tap-absence": {
    "null_default": "unobserved",           // Phase 1 reading of a stored null
    "empty_is_meaningful": false,           // is "" a distinct observed-empty state here?
    "convention": "req-grid-node-observation",
    "description": "Null = no source has captured a hardware address for this interface.",
    "not_applicable": {                     // Phase 2, reserved — declared, not yet consumed
      "permitted": true,
      "means": "Interface has no hardware address by nature (e.g. loopback/virtual)."
    }
  }
}
```

- `null_default` — the Phase-1 meaning of a stored `null` for this field. Effectively always `"unobserved"` under this convention; carried explicitly so the field is self-describing to a reader who doesn't know the convention.
- `empty_is_meaningful` — whether `""`/`[]`/`{}` is a distinct observed-empty state for this field (false for `mac_address`: a MAC is captured or it isn't).
- `description` — **required** (per the standing "JSON structures require descriptions" discipline); the human/AI gloss the code comment used to carry, now structured and flowing into the published schema.
- `not_applicable` — **Phase 2, reserved.** Declares whether N/A is *permitted* for this field and what it *means*. Present so the shape is fixed and external readers see the concept; not consumed until Phase 2 (Future). `permitted: false` is the default, under which a future per-cell N/A assertion is a validation error (FHIR's "absence channel must not bypass a binding" guard).

`x-tap-absence` is the source of truth for field absence-semantics; the `# noqa: DJ001` comment degrades to a pure lint-silencer (below).

#### The FLIP Hinge — Known vs Unknown Unknown

A bare `null` cannot, by itself, distinguish *"a source looked and asserts nothing is known"* from *"nobody has looked."* FLIP supplies the missing bit at zero additional cost, because an explicit write already earns a FLIP entry while an untouched field does not (see `spec-grid-flip.md` `req-grid-flip-default`, especially the patch semantics in `req-grid-flip-default-4`):

| Stored | FLIP entry for the field path | Interpretation |
| --- | --- | --- |
| `null` | **present** | **Known unknown** — a batch/actor explicitly asserted "unobserved." Someone looked and recorded the absence. |
| `null` | **absent** | **Unknown unknown** — no batch has ever touched this field. Open-world "no assertion," not a positive record. |

By design, an explicit `null` in a write payload is a *touched* field — stamped like any other value — while an omitted field is *untouched* and leaves both the column and its FLIP entry alone. This needs no new storage; FLIP is the already-built answer to the "horrific extra column" the responsibility axis would otherwise demand. The write pipeline realizes it (`req-grid-service-write-observation`): an explicit null is preserved (where the field permits null), clears the column, and is FLIP-stamped; FLIP is scoped to the touched fields, so an omitted field keeps its prior entry (or none). Absence of a FLIP entry is an open-world non-assertion, consistent with RDF's open-world assumption — it is never read as a positive "false."

#### The Inbound Write-Intent Boundary

Although a non-string column stores only two states, the *write boundary* must distinguish inbound *intent*, and the import/write path must preserve that intent long enough to apply it. Following FHIR's model — the writer declares absence-with-intent rather than the system inferring it from the stored value — intent is captured at the boundary, never reconstructed from the value:

| Inbound intent | Action |
| --- | --- |
| Field **absent** from the payload | Leave the prior stored value untouched (no clobber); do not stamp FLIP. |
| Field present and **explicitly `null`** | Set the column to `null` (assert unobserved) **and** stamp FLIP — recording that a source asserted the absence. |
| Field present with a value or `""` | Set the column and stamp FLIP. |
| **(Phase 2)** Field asserted **not-applicable** | Stored as `null`; the N/A flavor recorded out-of-band via extended FLIP (Future). Requires `x-tap-absence.not_applicable.permitted`. |

The GRIFT/import path (`spec-grid-import-grift.md`) and serializers must not flatten `absent` into `null` (or vice versa) on ingestion — doing so erases the known-vs-unknown distinction before the rule can act. `absent-in-batch ≠ observed-null`. Capturing intent explicitly at the boundary is also what lets Phase 2 distinguish an N/A assertion from a plain unobserved-null without overloading the value: the boundary carries the intent; the column stays `null`.

#### Not-Applicable — Codd's Third State (Phase 2, deferred)

Codd's *inapplicable* mark — an attribute with no meaningful value for an entity (a loopback interface's hardware MAC; a maiden name for someone never married) — is real and load-bearing (FHIR, SDMX, and DDI all found "missing" splits into at least *unobserved* vs *not-applicable*). TAP handles it in two layers:

- **Class-level inapplicability → the type system.** If an attribute is inapplicable to a whole kind of node, it is simply *not a column on that type* (or the node is a different type). An out-of-schema attribute on write is rejected by `additionalProperties: false`, not stored as a null. So class-level N/A never reaches a column — the type system absorbs Codd's I-mark for the common case. (Note also that nodes whose *identity is their value* — a Port's number, an IP's address — can never be N/A: the node would not exist without it.)
- **Instance-level inapplicability → out-of-band reason (Phase 2).** When N/A varies *within* a type — a loopback `network_interface` has no MAC while `eth0` does — the column stores `null` and the *not-applicable flavor* is recorded out-of-band. **The chosen direction is to extend FLIP** so a field's provenance entry carries applicability alongside the responsible batch: provenance grows to explain *why* the value is absent, rather than applicability becoming a separate parallel structure. (A dedicated `absence_map` column is rejected in favor of the FLIP extension; an in-band sentinel value is rejected outright — see Prior Art.)

Until Phase 2, `null` reads as unobserved everywhere; an instance that is genuinely N/A is indistinguishable from unobserved at the column level. That is an accepted Phase-1 limitation, not a defect.

#### The DJ001 Lint Deviation

Django's ruff rule `DJ001` forbids `null=True` on string-based model fields. TAP deliberately deviates where a string field's unobserved state is meaningful under this convention. The **declared `x-tap-absence` annotation is the authoritative justification**; the inline `# noqa: DJ001  (<RID>)` is only the lint-silencer ruff itself can see:

```python
mac_address = models.CharField(  # noqa: DJ001  (req-example-interface-1)
    max_length=17, blank=True, null=True
)
```

The `(<RID>)` cites the authorizing requirement (this convention, or a domain requirement that cites it), mirroring TAP's per-call-site justification tokens (`TAP-LOG-ID`, `TAP-AUTHZ-COV`): a narrow, auditable escape hatch, **not** a global rule-disable in `pyproject.toml`. The durable enforcement is a class-definition invariant (deferred — see Future): a nullable **service-writeable** field must carry `x-tap-absence`, and vice versa. The invariant is scoped to the observation surface (fields in `FIELD_CRUD_SCHEMA`/`SERVICE_CRUD_SCHEMA`); non-observation nulls — lifecycle (`closed_at=null` = still open), system actor (`actor=null` = system/deletion), control/pagination — are out of scope, and a service-writeable field that is genuinely a non-observation null may opt out with an explicit marker rather than be forced to declare absence semantics. A bare `# noqa: DJ001` with no RID should be rejected in review.

#### Prior Art

Every mature partial-data system keeps unobserved distinct from observed-empty, declares the *meaning* of absence as discoverable metadata, and represents that meaning *out-of-band* — never as an in-band sentinel. The cautionary tales come from collapsing distinctions or smuggling meaning into the value domain:

- **Cypher / property graphs** — `null` is a missing property; `""` is a real value. Adopt wholesale: `IS NULL`/`IS NOT NULL` as the unobserved predicates, `OPTIONAL`-style match to avoid silent drops, `coalesce` for explicit defaults.
- **HL7 FHIR `dataAbsentReason`** — the strongest direct hit: the value is absent and a *sibling element* carries a flat, opt-in reason code (`unknown`, `not-asked`, `masked`, `not-applicable`, …). Per-element, published, discoverable; the writer declares intent at the boundary; the reason lives out-of-band, never in the value. Two guards we adopt: (1) the absence channel must not bypass a value-set binding (if the domain already has an "unknown" member, use it); (2) present-but-blank must be a defined state, not an accident.
- **HL7 v3 / ISO 21090 `nullFlavor` — the cautionary tale.** The same codes, but a *mandatory hierarchical* code system requiring subsumption reasoning; widely judged unimplementable. FHIR's fix — flatten, make opt-in, rename honestly, forbid binding-bypass — is the sizing lesson: keep any flavor vocabulary small and flat.
- **SDMX `OBS_STATUS` ⟂ `CONF_STATUS`** — missing-ness is an out-of-band observation attribute on its *own axis*, separate from confidentiality, so one observation can be simultaneously missing and confidential. The reason TAP keeps absence-reason out of the value — here, folded into provenance — rather than overloading the stored value.
- **ISO/IEC 11179** — register each code's *Value Meaning* once and reuse it; the discipline behind `x-tap-absence.description` and its `convention` RID pointer.
- **Codd's relational model** — distinguished applicable-vs-inapplicable; SQL flattened them to one `NULL`. We re-derive the I-mark as Phase-2 N/A but represent it out-of-band (extended FLIP), not as Codd's second physical null.
- **SAS special missing (`.A`–`.Z`), Apache Arrow validity bitmap, `xsi:nil`** — every successful "kinds of missing" mechanism makes missing **structurally distinct** from the value domain (a reserved type-space, a bit beside the value, a type marker). The lesson that kills the in-band sentinel: **improbability ≠ structural distinctness** — a "weird value" (even a GUID) is still in the value domain, so it leaks to naive readers and can form false correlations; and it is *string-only* (an integer `port_number` or a boolean has no room for it), so it can never be the grid-wide rule.
- **RDF / open-world assumption** — absence means *unknown*, never *false*; the grounding for "no FLIP entry = open-world non-assertion."
- **Protobuf3** — *removed* field presence, then spent years re-adding `optional`; scar tissue for the asymmetric-cost argument that collapsing unobserved into a default is one-way data loss.
- **Prometheus / OpenTelemetry** — a hard structural line between "no sample" and "a sample of 0" (staleness markers) so an alert does not go silent when an exporter dies.
- **JSON Schema / OpenAPI** — unknown keywords are annotations, not errors (the `x-tap-absence` delivery mechanism); OpenAPI dropped the bare `nullable` boolean in 3.1 — a one-bit flag is too weak to carry meaning, which is why our annotation is a structured object. JSON Merge Patch's "null = delete" is the anti-pattern.
- **NetBox** (direct domain hit) — moved MAC from a string attribute to a first-class object (cardinality-zero = no MAC), and enforces the CMDB reconciliation rule that a discovery source which did not observe a field must not null out a prior value.

#### Status Details
Convention decided 2026-06-30 in design discussion, grounded in the prior-art pass above and staged into Phase 1 (here) / Phase 2 (extended-FLIP N/A, deferred). First adopted by `computing_core` (`mac_address`, `port_number`), which carry the `x-tap-absence` annotation. There is no central `BaseModel` enforcement of the annotation yet; grid-wide rollout is incremental, field by field, as node types are written or revised. This requirement documents the standing convention so adopters cite a single canonical home rather than re-deriving it per plugin.

**Dynamic-half realization (closed 2026-06-30).** The write-path enablement is now built in `spec-grid-service-write.md` `req-grid-service-write-observation` (`tap_grid/services.py` + `BaseModel.save`): (1) an explicit `null` is preserved where the field permits null, clearing the column and stamping FLIP; (2) FLIP is scoped to the touched fields via an explicit `flip_changed_fields` signal, so an omitted field is left alone; (3) create stamps only provided fields. The previously-named gaps (blanket `None`-strip; full-surface stamping; unspecified create semantics) are closed; `req-grid-node-observation-3`/`-4`/`-7` are Implemented. (The GRIFT node lane still sends full-object payloads routed through `replace_node`, so import-side "absent means no clobber" remains future reconciliation work — see Future.)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-node-observation-1 | Null Means Unobserved | Approved for Development | A column-backed field stores `null` to mean unobserved/unknown/not-applicable — never a sentinel value. | Cures "null island". |
| req-grid-node-observation-2 | Concrete-Empty Means Observed-Empty | Approved for Development | `""`/`[]`/`{}` mean a source observed the value to be empty, distinct from `null`. Non-string fields with no meaningful empty form are `null`-or-value only. | String fields are three-state; numeric two-state. |
| req-grid-node-observation-3 | FLIP Entry Distinguishes Known vs Unknown Unknown | Implemented | A `null` with a FLIP entry for that field path is a known unknown (a batch asserted the absence); a `null` with no FLIP entry is an unknown unknown (untouched). | Realized by `req-grid-service-write-observation`: explicit-null writes stamp FLIP; omitted fields do not. |
| req-grid-node-observation-4 | Three-State Inbound Write Boundary | Implemented | The write/import boundary distinguishes absent (leave prior, no clobber), explicit-null (clear + stamp FLIP), and present-value (set + stamp FLIP); ingestion must not flatten absent↔null. | Realized by `req-grid-service-write-observation` (absent / explicit-null / value at the pipeline boundary). |
| req-grid-node-observation-5 | DJ001 Deviation Carries A RID | Approved for Development | A string field using `null=True` under this convention carries `# noqa: DJ001  (<RID>)` citing the authorizing requirement — not a global rule-disable. | Mirrors `TAP-LOG-ID` / `TAP-AUTHZ-COV` annotation discipline; not yet machine-enforced (see Future). |
| req-grid-node-observation-6 | Absence Semantics Are Declared, Not Commented | Implemented | A field's absence meaning is declared in its `FIELD_CRUD_SCHEMA` entry via `x-tap-absence` (`null_default`, `empty_is_meaningful`, required `description`, `convention` RID), which auto-publishes through `SERVICE_CRUD_SCHEMA` to schema consumers. | Carrier is the existing field schema; no new plumbing. Non-validating annotation keyword. Acting on it in queries is Future (Gryphon). |
| req-grid-node-observation-7 | Inbound Write-Intent Captured At Boundary | Implemented | The write boundary captures intent (absent / explicit-null / value) explicitly rather than inferring it from the stored value, preserving absent-vs-null through ingestion. | FHIR-style; enables the Phase-2 N/A assertion. Write-path dependency. |
| req-grid-node-observation-8 | Not-Applicable Reserved For Phase 2 Via Extended FLIP | Proposed | Codd's not-applicable third state is declared in `x-tap-absence.not_applicable` and, when built, represented out-of-band by extending FLIP (provenance covers applicability) — never an in-band sentinel or a parallel column. Class-level N/A is absorbed by the type system. | Deferred; biased to extending FLIP per design decision. |

#### Future
Downstream dependencies are named here as deliberate considerations and left unbuilt (don't-overbuild filter); each belongs to a different spec and should be specified there when its surface is next worked:

- **Phase 2 — Not-Applicable via extended FLIP.** Resolve Codd's third state by extending FLIP's entry so a field path's provenance carries the absence *flavor* (e.g. `not-applicable`, `withheld`) alongside the responsible batch id, rather than standing up a parallel `absence_map`. Provenance thereby explains *why* a value is absent — applicability becomes part of provenance, not a separate concern (design decision, 2026-06-30). Consumes `x-tap-absence.not_applicable` and the inbound write-intent boundary. Touches `spec-grid-flip.md` (entry shape) and the write path. Biased direction, not yet specified.

- **Write-path enablement — DONE (2026-06-30).** Realized in `spec-grid-service-write.md` `req-grid-service-write-observation` (explicit-null preservation, FLIP scoped to touched fields, create-time semantics). Retained here only as the dependency pointer for the items below, which sit on top of it. Import-side reconciliation (no-clobber) remains future work (next bullet).
- **Query three-valued logic (traversal).** Once `null`-as-unobserved exists, the universal footgun is that *unknown silently behaves like false* in filters (SQL's `WHERE`/`NOT IN`/aggregate traps), so valid data vanishes from results. TAP's traversal (`spec-grid-traversal.md` / `spec-grid-traversal-language.md`) must specify how a predicate over an unobserved field resolves and ship first-class predicates — `IS UNOBSERVED` / `IS OBSERVED-EMPTY` / `IS KNOWN-UNKNOWN` (Phase 1, reading the column + FLIP) and `IS NOT-APPLICABLE` (Phase 2, reading the extended FLIP entry) — so nobody reconstructs them with fragile double-negatives. Gryphon reads `x-tap-absence` from the registry to surface these. Adopt Cypher's operators as the base.
- **Reconciliation no-clobber (import/write path).** `absent-in-batch ≠ observed-null`: a partial batch that did not observe a field must not overwrite a prior observed value with `null`. Collectors run live GRIFT batches today, so this is the dependency with present-day data-integrity teeth — flagged loudly for the owner of `spec-grid-import-grift.md` / the write path, deferred and tracked, not yet specified here.
- **Class-definition invariant (annotation + DJ001 enforcement).** Replace the noqa-scanner idea with a `BaseModel.__init_subclass__` invariant, mirroring the existing `_enforce_field_crud_schema` / `_enforce_field_validation_schema` class-definition checks: a nullable **service-writeable** field (one in `FIELD_CRUD_SCHEMA`) must carry an `x-tap-absence` entry and vice versa, and a `null=True` string field in that surface must carry the `# noqa: DJ001  (<RID>)` silencer. The invariant is deliberately scoped to the observation surface — lifecycle/system/control nulls (`closed_at`, `actor`, pagination) are not service-writeable observation fields and are excluded; a service-writeable field that is a genuine non-observation null opts out via an explicit `x-tap-absence` marker (e.g. `{"kind": "non-observation"}`) rather than declaring a flavor. This makes the declared annotation the machine-enforced source of truth and lets a bare/undocumented suppression fail at import. Requires auditing existing nullable fields across plugins, so deferred. Named, not built.

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

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
