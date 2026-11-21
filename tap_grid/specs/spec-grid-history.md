# Grid History Specification

## Philosophy

Grid history records how TAP's stored graph state changed over time. It exists to support auditability, debugging, bounded historical queries, and eventual time-travel traversal of the grid. History is a distinct capability from FLIP and perspective: history answers how TAP changed, not who currently owns a field and not how different observers see the world.

## Goals

|    |              |                                                                                   |
| :---: | ---       | ---                                                                               |
| 1. | Durable      | Changes to history-enabled nodes and edges are stored in a durable timeline        |
| 2. | Composable   | History queries can be scoped by time window and "latest before" semantics         |
| 3. | Independent  | History operates independently of FLIP and perspective configuration               |
| 4. | Time-Aware   | History distinguishes TAP record time from source observation time                 |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-history-backend | [History Backend and Independence](#history-backend-and-independence) | Proposed | Initial backend may use `django-simple-history`, but the capability is specified independently of the backend |
| req-grid-history-query | [Composable History Queries](#composable-history-queries) | Proposed | Query model must support bounded windows and latest-before semantics |
| req-grid-history-time | [History Time Semantics](#history-time-semantics) | Proposed | `recorded_at` is system-owned; `observed_at` is source/world time where available |
| req-grid-history-version | [Revision Metadata](#revision-metadata) | Implemented | Canonical entities carry a simple revision counter for lifecycle/debug metadata |
| req-grid-history-scope | [History Scope Configuration](#history-scope-configuration) | Proposed | History enablement and retention depth remain configurable per model/edge type |
| req-grid-history-reobservation | [Re-Observation Is Not A Change](#re-observation-is-not-a-change) | In Development | A write that changes nothing and asserts nothing new creates no history row and no new version |
| req-grid-history-optout | [Per-Model History Opt-Out](#per-model-history-opt-out) | Implemented | A node type declares `TRACK_HISTORY = False` to get no history table; default on; every consumer degrades explicitly; recorded on `EntityType.track_history`, checked for agreement, listed by the validator |

## Explanation

History is TAP's transaction-time memory. A history record exists because TAP stored a change, not because an external source observed something. That distinction matters because TAP will often ingest observations that happened earlier than they were recorded. In v1, the history capability should optimize for clear system behavior and queryability rather than full temporal-world reconstruction.

The target experience is a user-visible "dial" that can scope the grid to a time-bounded historical slice. The first implementation does not need to deliver full time-travel traversal, but it must not block it. The practical implication is that history must be query-oriented from the start, especially around `as_of`, `between`, and `latest_before` retrieval patterns.

### History Backend and Independence
----
RID: `req-grid-history-backend`

Status: `Proposed`

History is a standalone capability that may initially be backed by `django-simple-history`, but TAP must specify the behavior in grid terms rather than plugin terms. Models and edges may opt into history independently of FLIP and perspective.

#### Status Details
The current codebase already sketches this direction in `tap_flip` using `django-simple-history`. This requirement formalizes the expectation that the backend remains replaceable and that higher-level code should interact through TAP history services/adapters rather than direct plugin coupling.

#### Implementation
The initial implementation should:

1. Allow history to be enabled per model and per edge-capable type.
2. Record create, update, and delete snapshots for history-enabled objects.
3. Capture system transaction time for every history entry.
4. Capture actor information where available.
5. Expose history through a TAP service layer that can later swap storage backends.

History must not depend on FLIP data structures and must not require perspective records to exist. Perspective and FLIP may reference history behavior, but history remains independently configurable and queryable.

#### Development
The temptation to fold FLIP into history should be resisted. FLIP's job is to explain current field provenance cheaply. History's job is to provide a durable change timeline. Joining them too early would force identical retention and enablement behavior across capabilities that want different policies.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-backend-1 | Model-Level Enablement | Proposed | TAP supports enabling or disabling history per model or edge type without requiring FLIP or perspective on the same object type. | |
| req-grid-history-backend-2 | Service-Layer Access | Proposed | Application code retrieves history through TAP adapters/services rather than assuming a specific backend API. | |
| req-grid-history-backend-3 | Durable Change Events | Proposed | History-enabled objects record durable create, update, and delete timeline entries. | |

#### Future
Future work may replace the initial backend with a graph-native or append-only temporal model if query shape, performance, or retention policy needs outgrow the current approach.

### Composable History Queries
----
RID: `req-grid-history-query`

Status: `Proposed`

History must support composable, Postgres-friendly query patterns so TAP can bound search space by time and later support time-scoped graph traversal. The key requirement is query shape, not a specific SQL implementation.

#### Status Details
Not yet implemented in `tap_grid`. This requirement is intended to guide the history adapter and indexing strategy before historical UI and traversal features are built.

#### Implementation
The history query model must support, at minimum:

1. `timeline_for(subject)` returning a subject's ordered change history.
2. `between(start, end)` returning history rows in a bounded time window.
3. `latest_before(timestamp)` returning the latest known stored state prior to a cutoff.
4. `as_of(timestamp)` as a service-level composition over `latest_before`.
5. Additional filters such as model type, entity id, actor, and batch where available.

The implementation should be designed with indexable predicates and bounded queries in mind, similar to how row scoping is handled in multi-tenant systems. The goal is to avoid unbounded scans as the history corpus grows.

#### Development
The important architectural move here is to specify the query contract early. Whether the backing store is `django-simple-history` tables, a custom history table, or a later append-only event store, the rest of TAP should be coded against these grid-level query semantics.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-query-1 | Bounded Window Query | Proposed | History services can retrieve changes within a caller-specified time range. | |
| req-grid-history-query-2 | Latest Before Query | Proposed | History services can retrieve the latest stored entry prior to a specified timestamp. | Critical for future time-dial UX |
| req-grid-history-query-3 | Composable Filters | Proposed | Time filtering composes with subject and type filtering rather than requiring bespoke query paths for each case. | |

#### Future
Time-scoped graph traversal should build on these primitives rather than inventing a separate history access path.

### History Time Semantics
----
RID: `req-grid-history-time`

Status: `Proposed`

History must clearly distinguish TAP transaction time from source observation time. TAP owns transaction time. Sources provide observation time where relevant.

#### Status Details
This requirement is design-level guidance for the first implementation. It prevents ambiguity later when perspective records and historical replay need to coexist.

#### Implementation
The required semantics are:

1. `recorded_at` / transaction time is generated by TAP and is never trusted from the client.
2. `observed_at` is source/world time supplied by the write path when available.
3. History entries are ordered by TAP transaction time.
4. Historical reconstruction in v1 is defined in terms of TAP stored state, not full real-world temporal truth.
5. Perspective-enabled writes may also include `observed_at`, but that does not replace TAP's own recorded time.

In practice, transaction time may live on history rows and batch metadata, while observation time may live on perspective records or write payloads. The capability contract matters more than where the columns initially reside.

#### Development
This split preserves clarity:
- history explains when TAP changed
- perspective explains what a source said and when it observed it

Trying to collapse these into one timestamp would make both capabilities weaker.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-time-1 | Transaction Time Is System-Owned | Proposed | History entries use TAP-generated record time rather than client-supplied transaction timestamps. | |
| req-grid-history-time-2 | Observation Time Can Coexist | Proposed | History-capable write paths can carry source observation time without redefining history ordering semantics. | |
| req-grid-history-time-3 | V1 Is Transaction-Time History | Proposed | The first implementation defines historical reconstruction in terms of TAP stored state at a point in transaction time. | |

#### Future
Later work may add richer temporal semantics such as validity ranges or separate support for asserted-at versus observed-at when TAP begins handling analyst judgments in addition to direct observations.

### Revision Metadata
----
RID: `req-grid-history-version`

Status: `Implemented`

Canonical entities should carry a lightweight revision counter that increments on each canonical mutation. This is revision metadata for the object's lifecycle, not the source of truth for historical reconstruction.

#### Status Details
Proposed for early inclusion because it is cheap to add now and will be useful later for debugging, UI, and cache coordination.

#### Implementation
The revision metadata contract is:

1. `Entity.version` starts at `1` on creation.
2. The version increments on every canonical persisted mutation, including tombstone/delete transitions.
3. The version counter is updated through the service layer as part of normal writes.
4. The version counter does not replace history rows and is not used as the source of truth for point-in-time reconstruction.
5. The version counter is metadata about the current canonical revision, not a guarantee of exact equivalence to history-row count.

#### Development
This gives TAP a cheap monotonic "what revision is this object at?" capability without forcing history to depend on it. It should be treated as helpful metadata, not temporal truth.

Delete lifecycle semantics, including tombstoning and `deleted_at`, are owned by `spec-grid-service-delete.md`. History builds on that delete contract and records the final tombstone transition as part of the object's timeline.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-version-1 | Version Starts At One | Implemented | Canonical entities begin at version `1` when first created. | `Entity.version` default=1 |
| req-grid-history-version-2 | Version Increments On Mutation | Implemented | Every canonical mutation, including delete/tombstone, increments the entity's version. | `F("version") + 1` in BaseModel.save() and tombstone path |
| req-grid-history-version-3 | Version Is Metadata Not Truth | Implemented | Historical reconstruction does not rely on the version counter as the authoritative source of prior state. | |

#### Future
If version metadata proves useful in APIs and the viewer shell, TAP may later expose it through response metadata or badges without changing history semantics.

### History Scope Configuration
----
RID: `req-grid-history-scope`

Status: `Proposed`

History should remain configurable per model and edge type so TAP can selectively apply it where it adds value and control retention depth independently from FLIP and perspective policy.

#### Status Details
History policy remains its own concern even though the implementation may currently rely on model-level configuration surfaces. This requirement defines the policy concept without tying it to FLIP configuration.

#### Implementation
History scope configuration should support:

1. Whether history is enabled for a model/edge type.
2. Revision-count retention policy.
3. Time-based retention policy.
4. Future expansion to finer-grained inclusion rules if needed.

The implementation does not need to deliver all retention automation in the first pass, but the policy surface should be explicit and owned by TAP rather than hidden in backend defaults.

#### Development
Selective enablement matters because not every graph object needs equal temporal depth. A policy surface keeps history practical without forcing the entire grid into one retention posture.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-scope-1 | Explicit Enablement | Proposed | History policy includes an explicit enabled/disabled switch per model or edge type. | The per-model switch is built as `req-grid-history-optout`; per-edge-type, per-app and grid-wide switches are not. |
| req-grid-history-scope-2 | Retention Policy Surface | Proposed | History policy exposes revision-count and/or time-based retention settings even if cleanup automation is deferred. | |
| req-grid-history-scope-3 | Independent Policy | Proposed | History retention and enablement can differ from FLIP and perspective policy for the same model type. | |

#### Future
If the time-dial UI becomes central to the product, TAP may eventually need a more explicit "historical visibility" policy layer in addition to raw retention policy.

### Per-Model History Opt-Out
----
RID: `req-grid-history-optout`

Status: `Implemented`

A concrete node type may declare that TAP keeps no change history for it. History stays on by default; opting out is a per-type declaration in the type's own class body, and it removes the type's history table entirely rather than leaving an empty one.

#### Status Details
Built as the per-model slice of `req-grid-history-scope` (its `-1` switch, for node types only). Retention policy, per-edge-type enablement, and per-app or grid-wide settings stay with `req-grid-history-scope` and remain Proposed.

The cost it answers (measured, against a plugin declaring several hundred generated node types): `inherit=True` on the abstract base gives every concrete type a second table, so a plugin with N types migrates 2N tables, and every install pays it at boot.

#### Implementation
**Declaration.** `BaseModel.TRACK_HISTORY: ClassVar[bool] = True`. A subclass sets it to `False` in its class body, the same idiom as `INTERNAL_ONLY`. It is inherited like the other ClassVars, so an abstract intermediate can set it for a subtree. A value that is not a `bool` is refused at class creation (`ImproperlyConfigured`), because it decides whether a table exists.

**Record** (ruled aws-build Q82c, approved Q83, 2026-11-17). `EntityType.track_history` (`BooleanField`, default `True`, indexed) records the declaration in the type catalog, so an operator, the admin and any catalog reader can see which types keep no history without importing classes. It is a record, never a second source: registration stamps it from the class in the same `update_or_create` that stamps `name`, `icon`, `description` and `kind` — `TapPluginConfig._register_types_from_manifest` writes `getattr(cls, "TRACK_HISTORY", True)` for each manifest model, core's own `search` registration in `tap_grid/apps.py` writes `Search.TRACK_HISTORY`, and every edge type is written `True` because all edge types share the one `Edge` history table. Because the stamp runs on every load, flipping the flag moves the row at the next boot. The declaration stays on the class because simple-history decides at class definition and the migration generator reads the class; a database row can do neither.

**Agreement** (Q82c, Q83). `tap_grid.history.history_agreement_problems()` compares, for every node type in the entity-model registry, the class's `TRACK_HISTORY`, its `EntityType.track_history` (when a row exists: the registry and the catalog are different populations, so a missing row is not a disagreement), and whether a `Historical<Type>` model exists (`is_history_enabled`). It returns each type where any pair disagrees, naming the pairs (`class vs model`, `row vs class`, `row vs model`). It runs in a core test over every loaded type, and as the `grid.history_agreement` readiness probe. The probe is **not critical**: every consumer that acts on history asks the class-built answer and degrades explicitly with `HistoryNotTracked`, so a disagreement misdescribes a type in the catalog without leading a consumer to a wrong answer, and an absent history table is already `grid.tables`' critical failure. A disagreement turns the verdict `degraded` and names the types. If a consumer ever decides behaviour from the row, this ruling must be revisited.

**Visibility** (Q82c, Q83). `validate_plugin` at the loads level lists, under the check `history-opt-outs`, each of the plugin's node types whose class declares `TRACK_HISTORY = False`, as an **info** message and never a warning: opting out is the owner's decision, and plugin conformance runs `--strict`, which promotes warnings to failures.

**Mechanism** (read: django-simple-history 3.13 `HistoricalRecords.finalize`). The base declares `history = TapHistoricalRecords(get_user=..., inherit=True)`. simple-history builds each `Historical<Type>` model in `finalize`, on the concrete subclass's `class_prepared` signal, and offers no per-subclass exclusion for an inherited manager. `TapHistoricalRecords.finalize` returns before the stock body for a subclass whose `TRACK_HISTORY` is false, so that type gets no history model, no migration-state model, no `history` descriptor, no `simple_history_manager_attribute`, and no save/delete signal handlers. Every other sender runs the stock `finalize` untouched, which is why a type that does not opt out keeps exactly its prior history model and `makemigrations` reports no change.

**What an untracked type loses.** Prior field values: TAP can no longer say what the row looked like before its last change, who made an individual field change outside a batch, or when a value changed between two batches. `history_user` and `history_change_reason` have no row to sit on.

**What it keeps** (read: `Entity`, `BaseModel`, `BatchEvent`). The spine and the batch record are not history and are untouched: `Entity.version`, `created_at`, `updated_at`, `deleted_at`; the row's `batch_id` and `flip_map` (which batch last set each provenance-tracked field); and one `BatchEvent` per operation with its type, timestamp, actor and batch. An untracked type still answers who, when, through which batch and by which operation; it does not answer from what to what. A tombstone already writes no typed history row (Issue# 570 - tap), so retirement loses nothing further.

**When opting out fits.** A type whose rows are re-observed from a source on a schedule, so that its current state is always re-collectable and its prior states are mostly re-observation churn (Issue# 322 - tap). It does not fit where the grid itself is the only record of a past value — analyst-asserted data, configuration whose change over time is the question being asked (who opened this rule, when did this policy widen), or anything a time-dial or "what changed" view must answer. The owning plugin decides per type; the platform default stays on.

**Consumers and how each degrades** (grepped across core and installed plugins for `.history`, `history_user`, `Historical*`, `is_history_enabled`, `get_historical_records`, `simple_history`):

| Consumer | Behaviour for an untracked type |
| --- | --- |
| `HistoryService.raw_records()` / `get_historical_records()` | Raises `HistoryNotTracked` ("no history for this type"); `is_enabled()` is `False`. Never returns an empty timeline, which would read as "never changed". |
| `grid_tables.history_tables()` (ORM read backstop) | Names no history table for the type; the type's own table stays read-guarded. |
| `purge_node` and the GRIFT sweep-purge | Skip the history sweep: both already guard on the type having a `history` manager, which an untracked type lacks; the purge of the row, spine, touching edges and `BatchEvent`s is unchanged. |
| Admin | Only `Batch` uses `SimpleHistoryAdmin`, and core types keep history (`-7`). |
| GRIFT export / import | Neither carries history today (export declares the history lane not included; import discards it). |
| Batch actor (`get_history_user`) | Independent of history tables; batches and `BatchEvent`s still record the actor. |
| History panel, composable queries, time-travel reconstruction | Not built. When built, each must check `is_history_enabled` and present "no history for this type"; time-travel must report an untracked row updated after the cutoff as not reconstructable, never return its current state as the past. |

**Migration consequence.** Flipping the flag changes the owning app's next migration. `True → False` generates a `DeleteModel` for `Historical<Type>`: the recorded history of that type is dropped, irreversibly. `False → True` generates a `CreateModel`: the table starts empty and nothing is backfilled. The migration belongs to the plugin that owns the type, and a plugin generating it against a newer core than its floor must check its core dependency.

**Scope.** Node types only. Edges share one `Edge` table across every edge type, so a per-edge-type opt-out cannot be a table decision and is not offered; an untracked node's edges keep their history.

#### Development
The alternative, removing `history` from the base and registering per concrete class, would have touched every app's migration state to gain nothing the `finalize` override does not give. A Meta option was rejected because `BaseModel.Meta` is inherited by explicit `class Meta(BaseModel.Meta)` and Django refuses unknown Meta keys; a ClassVar matches `INTERNAL_ONLY` and `DEFAULT_DIMENSIONS`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-optout-1 | Default On | Implemented | `BaseModel.TRACK_HISTORY` is `True`; a type that does not declare it has a history manager and a `Historical<Type>` model, and introducing the mechanism produces no migration change for core or the default plugin set. | `makemigrations --check` clean |
| req-grid-history-optout-2 | No History Model | Implemented | A type declaring `TRACK_HISTORY = False` has no `Historical<Type>` model in the app registry or the migration state, no `history` attribute, and no history save/delete signal handlers. | |
| req-grid-history-optout-3 | Declaration Shape | Implemented | The declaration is a `bool` ClassVar, inherited through abstract intermediates; a non-`bool` value is refused at class creation. | |
| req-grid-history-optout-4 | Explicit Degradation | Implemented | Every built history consumer handles an untracked type explicitly: the history service raises `HistoryNotTracked` instead of returning empty, the read backstop names no history table, and purge and sweep-purge skip the history sweep without error. | Unbuilt consumers carry the same obligation (table above). |
| req-grid-history-optout-5 | Migration Consequence | Implemented | Opting out removes the history model from the migration state, so the owning app's next migration drops the history table (data loss); opting back in creates an empty one. | |
| req-grid-history-optout-6 | Spine Still Answers | Implemented | Writes to an untracked type through the service layer and GRIFT succeed, and the spine and batch record still carry version, timestamps, tombstone, `batch_id`, `flip_map` and per-operation `BatchEvent`s with actor. | |
| req-grid-history-optout-7 | Core Types Keep History | Implemented | `Edge`, `Batch`, `Dimension`, `Search` and `Keystone` keep history. | Edge history is shared across all edge types |
| req-grid-history-optout-8 | Recorded On EntityType | Implemented | `EntityType.track_history` (default `True`) is stamped from the class by every registration writer in the same `update_or_create` as `name` and `kind`: `getattr(cls, "TRACK_HISTORY", True)` for manifest models and core's `search`, `True` for every edge type. The class remains the authority. | Ruled aws-build Q82c, approved Q83 (2026-11-17) |
| req-grid-history-optout-9 | Agreement Check | Implemented | `history_agreement_problems()` reports every registered node type whose `TRACK_HISTORY`, `EntityType.track_history` (if a row exists) and `Historical<Type>` presence disagree, naming the disagreeing pairs. A core test asserts it is empty for the loaded types, and the `grid.history_agreement` readiness probe reports it, non-critical (verdict `degraded`). | Q82c, Q83; non-critical because no consumer decides from the row |
| req-grid-history-optout-10 | Validator Lists Opt-Outs | Implemented | `validate_plugin` (loads level) lists the plugin's node types declaring `TRACK_HISTORY = False` under `history-opt-outs` as info, never warning, so `--strict` conformance does not fail on an owner's decision. | Q82c, Q83 |

#### Future
Retention policy and per-app or grid-wide defaults remain under `req-grid-history-scope`. If re-observation stops creating history versions (Issue# 322 - tap), the cost case for opting out a re-collected type weakens on storage but not on migrate time, which scales with the number of tables, not rows.

### Re-Observation Is Not A Change
----
RID: `req-grid-history-reobservation`

Status: `In Development`

An object has three states with respect to any write pass: **changed**, **re-observed unchanged**, and **not observed**. History records the first. The second leaves no history row and no new version; it is recorded on the spine (`req-grid-entity-batch-pointers`) and in the batch's own record of what it observed.

#### Status Details
In Development. The classification and everything that reads it on the typed row and the batch are built (Issue# 322 - tap): `tap_grid/write_classification.py` and `_execute_write_pipeline` in `tap_grid/services/_impl.py`, with the GRIFT importer passing the envelope's spine values into the operation and the pipeline comparing them with the stored spine under the target's row lock (`spine_delta` in `tap_grid/write_classification.py`). The spine record of a re-observation is not built; it arrives with `req-grid-entity-batch-pointers`, and until then the batch's `observe` event is the only record that a batch saw an unchanged object.

Before this (run on core main, 2026-11-21, against a neutral fixture type), every write produced one typed history row and one `Entity.version` increment, whether or not anything changed. An identical GRIFT re-import wrote a row whose only differences from the previous row were `batch_id` and `flip_map`. On an instance collecting a real source on a ten-minute schedule this was measured at one history row per configuration object per pass (Issue# 322 - tap).

As built, "the object's spine `name` differs" in rule 2 means the name or natural key the model derives differs after the write, or a spine value the caller writes itself in the same batch differs (the GRIFT envelope's `name` and `dimensions`). A stored spine name that already disagrees with what the model derives, with nothing else different, is not a change: an unchanged re-observation no longer repairs it.

#### Implementation
1. The write pipeline classifies each update-shaped operation (patch, replace, keep-absent replace, and the GRIFT import of an existing object) as **changed** or **re-observed unchanged**, from the comparison `req-grid-flip-change` defines.
2. An operation is **changed** when any service-writeable value differs after the write, when any field is asserted for the first time (`req-grid-flip-change` rule 4), or when the object's spine `name` or `dimensions` differ. Everything else is **re-observed unchanged**.
3. A re-observed-unchanged operation does not save the typed row. It therefore writes no history row, does not increment `Entity.version`, does not move `Entity.updated_at`, and moves no FLIP entry.
4. A changed operation behaves as today: one history row, one version increment (`req-grid-history-version`, `req-grid-service-batch-occ` single-bump). This holds for a spine-only change as well: the typed row is saved and gains one history row even though no typed value differs, so every version keeps exactly one history row to carry its provenance.
5. The classification is made once per operation. FLIP, history, the version counter, the spine pointers and the batch's record of the operation all read that one result; none re-derives it.
6. A write that carries `entity_expected_version` is still checked against the stored version before classification, so a stale writer is refused whether or not its payload would have changed anything.
7. The operation still succeeds and still reports the object in its result. Callers cannot tell from success alone which state applied; the result says which (`WriteResult.state`: `changed` or `unchanged`).
8. `req-grid-history-version` rule 2 ("increments on every canonical persisted mutation") stays true: a re-observation persists no mutation.
9. The batch records a re-observed-unchanged operation as an `observe` event (`req-grid-service-batch-event`), where a changed one records `update`. Everything that reads a batch's events as proof of what it saw reads `observe` beside `create`, `update` and `link`.
10. Everything a save would do to the values happens before the classification, for every update-shaped operation: the model's write hook (`BaseModel.prepare_for_write`, where a model normalises or derives a stored value), field and record validation, and an edge's property schema. An operation found unchanged has therefore skipped no check and lost no derived value. The comparison covers every column the typed row stores, system-managed fields excluded, so a value the hook derives off the service-writeable surface still makes the operation a change.
11. The classification is made on the complete operation under the target's row lock. A caller that also writes spine values for the target in the same batch (the GRIFT envelope's name and dimensions) hands those values to the operation; the pipeline, not the caller, compares them with the stored spine, and the caller's write of them happens in the same transaction, under the same lock.

#### Development
"What changed since last week" reads history. While re-observation is recorded as change, the answer is "everything, on every pass". The fix is in the write path and not in compaction, because a version run that is later compacted has already moved every FLIP entry and every `updated_at`.

A source field that really does differ on every pass (a scan timestamp written into the payload) is a change and is recorded as one. Suppressing it is the source's decision, not the grid's.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-reobservation-1 | Identical Re-Import Leaves No Row | Implemented | Importing the same object twice in two batches leaves one history row, `Entity.version` at 1 and `Entity.updated_at` unmoved. | `tap_grid/tests/test_write_classification.py`: `test_identical_reimport_leaves_no_row` |
| req-grid-history-reobservation-2 | One Change, One Row | Implemented | A later import that changes one field adds exactly one history row and one version, and the row differs from its predecessor in that field and in provenance only. | `tap_grid/tests/test_write_classification.py`: `test_one_change_one_row` |
| req-grid-history-reobservation-3 | Same-Value Patch Leaves No Row | Implemented | `patch_node` and `replace_node` sending only stored values add no history row and no version. | `tap_grid/tests/test_write_classification.py`: `test_same_value_write_leaves_no_row` |
| req-grid-history-reobservation-4 | Spine-Only Change Is A Change | In Development | A re-import that changes only the envelope `dimensions` is classified changed: the version increments once, exactly one typed history row is added, and the spine pointers move. | The version, the one history row and the `update` event are built (`tap_grid/tests/test_write_classification.py`: `test_spine_only_change_is_a_change`). The spine pointers are `req-grid-entity-batch-pointers`, not built. |
| req-grid-history-reobservation-5 | First Assertion Is A Change | Implemented | The first explicit `null` on a field with no FLIP entry adds one history row and one version; repeating it adds none. | `tap_grid/tests/test_write_classification.py`: `test_first_assertion_is_a_change_and_its_repeat_is_not` |
| req-grid-history-reobservation-6 | Stale Writer Still Refused | Implemented | An unchanged payload carrying a stale `entity_expected_version` is refused with `entity_version_conflict`. | `tap_grid/tests/test_write_classification.py`: `test_stale_writer_is_still_refused` |
| req-grid-history-reobservation-7 | Result Names The State | Implemented | The operation's result distinguishes changed from re-observed unchanged. | `tap_grid/tests/test_write_classification.py`: `test_result_names_the_state` |
| req-grid-history-reobservation-8 | Edges Included | Implemented | The same rules hold for edge replace and for an edge re-imported unchanged. | `tap_grid/tests/test_write_classification.py`: `test_edge_replace_follows_the_same_rules`, `test_edge_reimported_unchanged_leaves_no_row` |
