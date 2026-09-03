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
| req-grid-history-scope-1 | Explicit Enablement | Proposed | History policy includes an explicit enabled/disabled switch per model or edge type. | |
| req-grid-history-scope-2 | Retention Policy Surface | Proposed | History policy exposes revision-count and/or time-based retention settings even if cleanup automation is deferred. | |
| req-grid-history-scope-3 | Independent Policy | Proposed | History retention and enablement can differ from FLIP and perspective policy for the same model type. | |

#### Future
If the time-dial UI becomes central to the product, TAP may eventually need a more explicit "historical visibility" policy layer in addition to raw retention policy.
