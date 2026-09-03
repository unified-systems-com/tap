# Grid Hotlink Specification

## Philosophy

Hotlinks standardize the case where a node stores one or more references in its own data, while the graph also materializes those same relationships as typed edges. Without a formal contract, the node payload and the edge set can drift apart: a node may name things that no longer have edges, or edges may continue to exist after the node stops referencing them.

The hotlink system makes this relationship explicit at the model level. Models declare `HOTLINKS` as authoritative metadata describing where references live inside their fields and how those references map onto edges. The service layer uses that declaration to validate graph consistency during writes.

Hotlinks do not replace edges and do not make embedded references authoritative. The edge remains the graph-level relationship. The hotlink declaration exists to define the contract between a node's embedded reference data and the corresponding edge set.

In addition to the model-level declaration, participating edges carry explicit hotlink instance data in `properties.hotlink`. This makes hotlink participation obvious when inspecting an edge directly, without secondary inference from ad hoc property keys.

## Goals

|    |               |                                                                                              |
| :---: | ---        | ---                                                                                          |
| 1. | Standardized   | Models declare node-to-edge reference mappings in one consistent structure                    |
| 2. | Validated      | Service-layer writes can verify that embedded references and edge materialization agree       |
| 3. | Extensible     | Multiple selector backends can be supported over time without changing the top-level contract |
| 4. | Incremental    | Existing model behavior can adopt hotlinks declaratively without rewriting read-time logic    |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-hotlink-model | [Hotlink Model Declaration](#hotlink-model-declaration) | Implemented | `HOTLINKS` on `BaseModel` subclasses is the source of truth |
| req-grid-hotlink-edge-data | [Hotlink Edge Instance Data](#hotlink-edge-instance-data) | Implemented | Participating edges carry explicit `properties.hotlink` metadata |
| req-grid-hotlink-selector | [Hotlink Selector System](#hotlink-selector-system) | Implemented | v1 uses a simple TAP path selector; selector backends are pluggable |
| req-grid-hotlink-validation | [Hotlink Validation Semantics](#hotlink-validation-semantics) | Implemented | Service layer validates extracted references against edges |
| req-grid-hotlink-deferred | [Deferred Validation In Batch Contexts](#deferred-validation-in-batch-contexts) | Implemented | Multi-op batches defer hotlink checks until all node + edge writes have landed, then drain before commit |
| req-grid-hotlink-mutation | [Hotlink Mutation Boundaries](#hotlink-mutation-boundaries) | Proposed | Reverse edge-mutation protection is a planned next phase |

## Explanation

The canonical motivating example is the page-to-panel mapping in `tap_web`. A `Page` stores panel identifiers inside its `layout` JSON field. The actual graph linkage is expressed by outbound `USES_PANEL` edges. Today the join is performed through `properties["panel-id"]`. The hotlink system replaces that loose property convention with an explicit `properties.hotlink` object and a model-level declaration that formalizes:

1. which field contains the embedded references,
2. how to extract the identifiers from that field,
3. which edge type the identifiers correspond to, and
4. how the edge's hotlink instance data identifies the hotlink definition and carries the matched value.

With that declaration in place, the service layer can validate hotlink consistency when saving the node. For `Page`, the intended invariant is `exact`: the set of panel IDs extracted from `layout` must exactly match the set of `hotlink.value` values found on the page's relevant `USES_PANEL` edges whose `hotlink.model` is `page` and whose `hotlink.spec` is `page-panels`.

The hotlink system is intentionally defined as a generic `tap_grid` feature, not a page-specific validator. Other models will eventually use other selector backends, such as structured extraction from XML or free text. The top-level contract should stay stable while selector implementations evolve underneath it.

### Hotlink Model Declaration
----
RID: `req-grid-hotlink-model`

Status: `Implemented`

Concrete `BaseModel` subclasses may declare a class-level `HOTLINKS` registry describing embedded references that correspond to graph edges. `HOTLINKS` is the authoritative declaration of hotlink behavior. Participating edges carry instance-level hotlink data, but they do not define hotlink meaning on their own.

#### Status Details
Implemented in `tap_grid`. `HOTLINKS` is a `ClassVar[list[dict]]` on `BaseModel`. Startup validation runs in `__init_subclass__` via `_check_hotlinks`. `Page` in `tap_web` carries the first concrete declaration.

#### Implementation
`HOTLINKS` is a class variable on a `BaseModel` subclass. It is a list of hotlink definition objects. Each definition describes one mapping between embedded references in the node and one family of edges.

Each hotlink definition includes:

| Key | Required | Description |
| --- | --- | --- |
| `name` | Yes | Stable identifier for the hotlink definition within the model |
| `field` | Yes | Model field name containing the source data to inspect |
| `selector_type` | Yes | Extraction backend identifier, such as `path` in v1 |
| `selector` | Yes | Selector string interpreted by the chosen backend |
| `edge_direction` | Yes | Direction of the corresponding edges relative to the node, such as `outbound` |
| `edge_type` | Yes | Edge type that materializes the embedded references |
| `mode` | Yes | Validation mode: `exists`, `unique`, or `exact` |

Optional metadata may be added later, but v1 should remain intentionally narrow.

Conceptual example for `Page`:

```python
HOTLINKS = [
    {
        "name": "page-panels",
        "field": "layout",
        "selector_type": "simple_path",
        "selector": "columns.*.rows.*.panel-id",
        "edge_direction": "outbound",
        "edge_type": "USES_PANEL",
        "mode": "exact",
    }
]
```

This declaration does not change the existing read path. It only formalizes the contract that the service layer can enforce.

#### Development
Keeping `HOTLINKS` separate from `FIELD_VALIDATION_SCHEMA` is intentional. `FIELD_VALIDATION_SCHEMA` governs field shape and field-level validation. Hotlinks govern graph consistency between a node payload and materialized edges. Mixing the two would blur schema validation and relationship validation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-hotlink-model-1 | Model-Level Registry | Implemented | A `BaseModel` subclass may declare `HOTLINKS` as a class-level list of definition objects. | |
| req-grid-hotlink-model-2 | Authoritative Definition | Implemented | `HOTLINKS` is the authoritative declaration of hotlink meaning; edge hotlink data identifies participation but does not redefine the contract. | |
| req-grid-hotlink-model-3 | Narrow Required Keys | Implemented | Each hotlink definition must declare `name`, `field`, `selector_type`, `selector`, `edge_direction`, `edge_type`, and `mode`. | |
| req-grid-hotlink-model-4 | Multiple Definitions Supported | Implemented | A model may declare more than one hotlink definition when multiple embedded reference systems exist. | |

#### Future
Startup validation of `HOTLINKS` declarations is now implemented alongside `FIELD_VALIDATION_SCHEMA` via `_check_hotlinks` in `__init_subclass__`.


### Hotlink Edge Instance Data
----
RID: `req-grid-hotlink-edge-data`

Status: `Implemented`

Edges that participate in a hotlink carry explicit instance data in `properties.hotlink`. This makes the hotlink visible on the edge itself and provides enough information for readers to resolve the owning model and hotlink definition through the entity model registry.

#### Status Details
Implemented. Seeder and service layer write `properties.hotlink`. `page_service.get_page_panels()` reads `hotlink.value`. Data migration `tap_web/migrations/0005` backfills existing edges.

#### Implementation
Participating edges store a reserved `hotlink` object inside `properties`:

```json
{
  "hotlink": {
    "model": "page",
    "spec": "page-panels",
    "value": "main"
  }
}
```

Field meanings:

| Key | Description |
| --- | --- |
| `model` | The entity type slug of the model that declared the hotlink definition, such as `page` |
| `spec` | The `HOTLINKS[].name` value on that model, such as `page-panels` |
| `value` | The specific identifier value this edge materializes for that hotlink instance |

The resolution path is:

1. read `properties.hotlink.model`,
2. resolve the model class via the entity model registry,
3. inspect that model's `HOTLINKS`,
4. find the definition whose `name` matches `properties.hotlink.spec`.

The edge-side hotlink object is intentionally narrow. It should not duplicate selector configuration, validation mode, field names, or other model-level contract data.

This change requires the current page/panel implementation to migrate away from the loose `properties["panel-id"]` convention. The `USES_PANEL` edge payload and the surrounding panel-id handling code will need to write and read `properties.hotlink.value` instead. The page layout format remains the source of embedded panel identifiers, but the join contract between layout and edges now uses the explicit hotlink object.

#### Development
Making hotlink participation explicit on the edge improves debuggability and future mutation protection. A reader inspecting an edge no longer has to infer that a field like `panel-id` is participating in a hotlink contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-hotlink-edge-data-1 | Explicit Edge Object | Implemented | An edge participating in a hotlink stores a `properties.hotlink` object rather than relying on an ad hoc top-level join key. | |
| req-grid-hotlink-edge-data-2 | Globally Qualified Reference | Implemented | `properties.hotlink` includes `model` and `spec`, allowing readers to resolve the hotlink definition without hidden context. | |
| req-grid-hotlink-edge-data-3 | Value Stored On Edge | Implemented | `properties.hotlink.value` stores the identifier value materialized by that edge instance. | |
| req-grid-hotlink-edge-data-4 | No Redundant Contract Data | Implemented | Edge-side hotlink data does not duplicate selector rules, validation mode, or other model-level contract fields. | |
| req-grid-hotlink-edge-data-5 | Page Panel Migration Required | Implemented | The existing page/panel implementation must migrate from `properties[\"panel-id\"]` to `properties.hotlink` and update the panel-id handling path accordingly. | |

#### Future
If needed, additional edge-side metadata may be added under `properties.hotlink`, but only when it clearly represents edge-instance state rather than duplicated model definition.


### Hotlink Selector System
----
RID: `req-grid-hotlink-selector`

Status: `Implemented`

Hotlink extraction is selector-based. The selector system must be pluggable, but v1 should start with a deliberately simple selector backend for structured JSON traversal.

#### Status Details
Implemented. `_simple_path_extract` in `tap_grid/hotlink.py` handles `simple_path` traversal. `extract_identifiers` dispatches by `selector_type`. Additional backends can be added without changing the top-level contract.

#### Implementation
The selector system is defined by two fields on each hotlink definition:

| Field | Meaning |
| --- | --- |
| `selector_type` | Identifies which extraction backend interprets the selector |
| `selector` | Backend-specific expression describing where identifiers are found |

V1 uses `selector_type = "simple_path"`. This selector type is a TAP-native traversal syntax intended for deterministic extraction from structured JSON. It is not JSONPath, and it should not be described as a JSONPath subset.

For the page layout example, the selector:

```text
columns.*.rows.*.panel-id
```

means:

1. start at the `layout` field root,
2. descend into every entry under `columns`,
3. descend into every entry under `rows`,
4. collect the value at `panel-id`.

The v1 path selector should support straightforward object traversal and wildcard fan-out. It should remain intentionally constrained so model declarations are stable, easy to review, and easy to reason about.

Future selector backends may include:

| `selector_type` | Intended Use |
| --- | --- |
| `jsonpath` | Standardized JSON querying when a model truly needs richer selection semantics |
| `xml` | Attribute or node extraction from XML payloads |
| `text` | Structured extraction from free text using a dedicated parser |

#### Development
The decision to start with a simple path selector is pragmatic. Hotlink validation needs stable ID extraction, not general-purpose query semantics. Standard JSONPath libraries vary in behavior and would add complexity before the project has a demonstrated need for that flexibility.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-hotlink-selector-1 | Selector Type Required | Implemented | Every hotlink definition declares a `selector_type`. | |
| req-grid-hotlink-selector-2 | V1 Simple Path Selector | Implemented | `selector_type = "simple_path"` is supported for deterministic traversal of structured JSON fields. | |
| req-grid-hotlink-selector-3 | Backend-Pluggable Contract | Implemented | Additional selector backends may be added later without changing the top-level `HOTLINKS` contract. | |
| req-grid-hotlink-selector-4 | No Implicit JSONPath Claim | Implemented | The v1 path selector is TAP-specific and is not presented as JSONPath compatibility. | |
| req-grid-hotlink-selector-5 | Scalar Backend | Implemented | `selector_type = "scalar"` returns the field's own value as the sole identifier (empty/null → no identifier); `selector` is unused. For fields whose value *is* the reference (e.g. a URL/id in a CharField), which `simple_path` cannot serve. | First user: `rekor_log_entry.signing_identity_issuer` → `IDENTITY_VOUCHED_BY`. |

#### Future
When a concrete use case requires it, define a separate requirement for `selector_type = "jsonpath"` with an explicitly chosen library or dialect and a compatibility policy.


### Hotlink Validation Semantics
----
RID: `req-grid-hotlink-validation`

Status: `Implemented`

The service layer uses `HOTLINKS` declarations to validate that embedded references and materialized edges stay synchronized. Validation operates on identifiers extracted from the node field and identifiers collected from matching edges.

#### Status Details
Implemented. `validate_hotlinks` in `tap_grid/hotlink.py` is called from `BaseModel.full_validate()`. Skips validation when `entity_id is None` (first save, Option A). All three modes (`exact`, `exists`, `unique`) are implemented.

#### Implementation
For each hotlink definition on a model instance being saved, the validator:

1. reads the declared `field` value from the node,
2. extracts zero or more identifiers using the declared selector backend,
3. queries the corresponding edge set for that node using `edge_direction` and `edge_type`,
4. filters to edges whose `properties.hotlink.model` and `properties.hotlink.spec` identify the current hotlink definition,
5. collects the value of `properties.hotlink.value` from each matching edge,
6. applies the declared `mode` to compare extracted identifiers against edge identifiers.

Validation modes:

| Mode | Meaning |
| --- | --- |
| `exists` | Every extracted identifier must have at least one matching edge identifier |
| `unique` | Every extracted identifier must have exactly one matching edge identifier |
| `exact` | The extracted identifier set and the matching edge identifier set must be equal |

The `exact` mode is the intended invariant for page-to-panel mappings. It prevents both kinds of drift:

- missing edges for identifiers still referenced by the node, and
- lingering edges whose identifiers are no longer referenced by the node.

Hotlink validation is graph-consistency validation. It does not replace schema validation of the underlying field. For example, a page `layout` still needs its own JSON-schema-based shape validation independent of any hotlink definition.

#### Development
This separation of concerns is important:

- `FIELD_VALIDATION_SCHEMA` or equivalent validators answer: "Is the field structurally valid?"
- `HOTLINKS` answer: "Does this field's embedded reference contract agree with the graph?"

The system should validate against the node's current persisted edges at save time. That keeps the first implementation simple and allows existing models to adopt hotlinks declaratively.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-hotlink-validation-1 | Extract Then Compare | Implemented | Validation extracts identifiers from the declared field and compares them against identifiers collected from matching edges. | |
| req-grid-hotlink-validation-2 | Direction-Aware Edge Query | Implemented | The validator uses `edge_direction` and `edge_type` to identify which edges participate in the hotlink comparison. | |
| req-grid-hotlink-validation-3 | Join via Hotlink Object | Implemented | The validator uses `properties.hotlink.model`, `properties.hotlink.spec`, and `properties.hotlink.value` to identify and match participating edges. | |
| req-grid-hotlink-validation-4 | Exact Mode Enforces Equality | Implemented | In `exact` mode, validation fails unless the identifier sets from the node and edges are equal. | |
| req-grid-hotlink-validation-5 | Independent of Field Shape Validation | Implemented | Hotlink validation does not replace or weaken existing field-structure validation. | |

#### Future
Consider exposing a reusable reconciliation helper that computes both identifier sets and returns a structured diff for admin tooling, diagnostics, and future write orchestration.


### Deferred Validation In Batch Contexts
----
RID: `req-grid-hotlink-deferred`

Status: `Implemented`

A node's hotlink contract is a statement about the *post-batch* graph, not about the graph as it exists during the per-row save inside that batch. When a multi-operation write batch replaces a node whose embedded references point at edges the same batch is about to create, validating the node at save time sees a stale edge set and rejects a write that is in fact consistent after the batch lands. Deferred validation moves the hotlink check to the end of the batch, after every node and edge write has been staged but before the transaction commits, so the validator sees the graph the caller actually declared.

This requirement specifies *when* hotlink validation runs in a batch context. It does not change the semantics defined in `req-grid-hotlink-validation`; the same extract-and-compare logic runs, just at a different point in the pipeline.

#### Status Details
Implemented. `tap_grid/caller_context.py` exposes a side-channel ContextVar (`_pending_hotlink_checks`) that batched writes activate. `validate_hotlinks` in `tap_grid/hotlink.py` consults it and enqueues `(model_cls, entity_id)` instead of validating inline when deferral is active. `write_batch` in `tap_grid/services.py` drains the queue after the ops loop and before the atomic commit, attributing failures back to the originating `WriteResult`. See `req-grid-service-batch-precommit-consistency` in `spec-grid-service-batch.md` for the batch pipeline's view of the same phase.

#### Implementation

**Opt-in via context.** Hotlink deferral is opt-in for a write scope, not the global default. The deferral state lives in a ContextVar separate from `CallerContext` (which is frozen). When the queue is `None`, validation runs inline as defined in `req-grid-hotlink-validation` (preserves direct-`model.save()` semantics). When the queue is a list, validation enqueues and returns immediately.

**Activated by `write_batch` (not the per-op pipeline).** The activation happens at the batch boundary: `write_batch` enables the queue at the top of its `transaction.atomic()` block, runs all per-op pipelines under deferral, then drains. Per-op pipeline `full_validate()` calls participate transparently. Nested re-entry of `write_batch` is not supported in v0 (one batch context per write scope).

**Drain timing.** The drain runs after the ops loop, after every per-op pipeline has reported `success=True`, and before the dry-run rollback / commit. If any per-op pipeline failed, the batch has already short-circuited; no drain is needed since the atomic block will roll back regardless.

**Drain disables further deferral.** Before the drain re-runs `validate_hotlinks` on each enqueued instance, the ContextVar is reset to `None`, so the re-entrant validate call performs inline validation against the now-current edge set. This avoids self-deferring loops.

**All-failures collection.** The drain pass iterates the full queue and collects every hotlink failure. It does not bail on the first failed entity. The result is a complete picture of which nodes the bundle left inconsistent, mirroring the existing all-fields-collected behavior inside a single `validate_hotlinks` call.

**Per-operation failure attribution.** Each enqueued entry carries `entity_id`. After the drain collects errors, each error is attributed to the `WriteResult` of the operation whose `entity_id` matches — flipping that result to `success=False` and appending the hotlink error. This makes the failure surface inside `BatchWriteResult.results` legible to the same per-op machinery that surfaces validation errors today (e.g. the GRIFT importer's `_BatchFailed` path attaches per-op messages to its issues list). If multiple operations in the same batch touched the same `entity_id`, the failure attributes to the last such operation, which is the one whose declared state is being measured.

**Rollback on any failure.** Any error collected during the drain causes the atomic block to roll back, identical to a per-op failure. The batch is all-or-nothing; partial hotlink consistency is never persisted.

#### Boundaries

- Direct `model.save()` (outside the service layer) keeps inline hotlink validation. The deferral mechanism is local to `write_batch` callers.
- Dry-run mode runs the drain like a real commit. A dry-run that would have failed hotlink validation reports the same per-op failure set; the atomic rolls back as it always does for dry-run.
- The Option A first-save skip (`entity_id is None`) is still honored in the inline path. In the deferred path, fresh-create ops also defer; their `entity_id` is set by the pipeline before the drain runs, so the drain validates them against the now-attached edges.
- Hotlink failures discovered in the drain emit a stable error code `hotlink_validation_failed` distinct from per-op `validation_error`, so callers can distinguish "node payload was malformed" from "batch left the graph inconsistent".

#### Development
The structural insight: hotlink consistency is a *whole-batch* property, not a *per-row* property. The per-row save is the wrong place to check it because nothing about a row's payload, taken in isolation, can answer the question — the answer depends on what other rows in the same batch do. Per-row validation was the natural starting point and worked while the only writes were single-row, but multi-op batches surface the mismatch. The fix is to push the check to the boundary where the question is actually answerable.

This is also why deferral lives in `tap_grid` and not in the GRIFT importer: any caller assembling a multi-operation write that mixes node payloads with their materializing edges hits the same shape (importer, future bulk admin APIs, scripted writes, future federation paths). Putting the deferral in `write_batch` covers all of them with one mechanism.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-hotlink-deferred-1 | Opt-In Deferral State | Implemented | A side-channel ContextVar carries the deferred-hotlink queue; deferral is inactive (queue is `None`) by default and activated by batch contexts. | Inline `model.save()` outside a batch keeps existing behavior. |
| req-grid-hotlink-deferred-2 | Validate Enqueues Under Deferral | Implemented | When deferral is active, `validate_hotlinks` appends `(model_cls, entity_id)` and returns instead of running inline. | The Option A first-save skip still suppresses enqueue for unsaved instances. |
| req-grid-hotlink-deferred-3 | Drain Runs At Batch End | Implemented | The drain runs after all per-op pipelines succeed and before commit / dry-run rollback, inside the same atomic block. | If any per-op pipeline already failed, no drain is needed. |
| req-grid-hotlink-deferred-4 | Drain Disables Deferral | Implemented | The drain resets the ContextVar before re-invoking `validate_hotlinks` so the re-entrant call validates inline. | Prevents self-deferring loops. |
| req-grid-hotlink-deferred-5 | All Failures Collected | Implemented | The drain iterates every enqueued entry and collects every hotlink failure rather than stopping at the first failure. | Mirrors the all-fields behavior inside a single `validate_hotlinks` call. |
| req-grid-hotlink-deferred-6 | Per-Op Failure Attribution | Implemented | Each hotlink failure is attributed to the `WriteResult` whose `entity_id` matches the enqueued entry; that result is flipped to `success=False` with the failure appended. | Failure code is `hotlink_validation_failed`. |
| req-grid-hotlink-deferred-7 | All-Or-Nothing Rollback | Implemented | Any drain failure causes the atomic block to roll back. The batch never partially persists with inconsistent hotlinks. | Identical commit semantics to a per-op failure. |
| req-grid-hotlink-deferred-8 | Stable Failure Code | Implemented | Drain failures use the code `hotlink_validation_failed`, distinct from per-op `validation_error`. | Lets callers distinguish payload errors from batch-level graph-consistency errors. |

#### Future
A natural extension is a generalized "before-commit graph-consistency phase" hook that other future consistency checks could register against (`req-grid-service-batch-precommit-consistency` mentions this as an explicit future seam). Hotlinks are the only current consumer; widen the surface only when a second use case lands.


### Hotlink Mutation Boundaries
----
RID: `req-grid-hotlink-mutation`

Status: `Proposed`

Validating hotlinks only when saving the node catches invalid node writes, but it does not fully prevent desynchronization. Edge deletion or mutation can still invalidate a node that is not currently being saved. A later phase should define reverse protection for edge mutations that impact declared hotlinks.

#### Status Details
This is intentionally deferred. The first milestone is node-save validation based on `HOTLINKS`. Reverse edge-mutation enforcement will be specified separately once the initial implementation exists.

#### Implementation
Future edge-mutation protection should use the model-level `HOTLINKS` registry as its source of truth, while consulting explicit `properties.hotlink` data on participating edges.

For an affected hotlink definition, mutating any of the following may need protection or coordinated reconciliation:

| Mutation Kind | Why It Matters |
| --- | --- |
| edge deletion | Can remove the only materialized relationship for an embedded reference |
| `from_entity` / `to_entity` changes | Can move the relationship away from the node whose payload still references it |
| `edge_type` changes | Can move the edge out of the hotlink's declared edge family |
| `properties.hotlink.model` / `spec` / `value` changes | Can break the identifier match or detach the edge from the intended hotlink contract without deleting the edge |

The likely long-term model is:

1. generic validators prevent invalid low-level writes, and
2. higher-level reconciling services update node payloads and edge sets together when a coordinated change is intended.

#### Development
Edge-side hotlink metadata is now part of the design, but it remains instance-level participation data rather than a second source of truth for hotlink meaning.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-hotlink-mutation-1 | Model Registry Remains Source of Truth | Proposed | Future reverse mutation protection derives hotlink meaning from model `HOTLINKS`, not from user-authored edge flags. | |
| req-grid-hotlink-mutation-2 | Edge Writes Recognize Contract Fields | Proposed | Future reverse mutation protection treats deletion, endpoint changes, edge-type changes, and join-key changes as contract-sensitive operations when a hotlink depends on them. | |
| req-grid-hotlink-mutation-3 | Coordinated Reconciliation Path | Proposed | The system should eventually support a higher-level write path that updates node payload references and edge materialization together. | |

#### Future
If reverse lookup cost becomes significant, consider derived edge metadata or a reverse index to accelerate "which hotlinks depend on this edge?" queries without making that metadata authoritative.
