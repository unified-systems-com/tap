# Grid History Time-Travel Specification

## Philosophy

Time travel is the point-in-time projection of the TAP graph at a chosen transaction-time cutoff. It is built on top of core history and delete lifecycle semantics, but it is its own capability: a caller asks for the world as it existed at a specific time, and TAP reconstructs that state through service-layer reads and searches.

The first implementation is intentionally narrow. It supports strict point-in-time reads and searches only. It does not yet attempt range semantics, ghosted future objects, replay modes, or write operations while time traveling.

## Goals

|    |              |                                                                                          |
| :---: | ---       | ---                                                                                      |
| 1. | Point-In-Time | TAP can return the graph as it existed at a specific transaction-time cutoff            |
| 2. | Service-Layer | Historical projection is owned by TAP services rather than hidden ORM magic             |
| 3. | Efficient     | Current canonical timestamps are used as a first-pass optimization before history lookup |
| 4. | Honest        | Returned historical objects are marked as historical in response metadata                |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-history-tt-scope | [Time-Travel Scope](#time-travel-scope) | Proposed | V1 supports strict point-in-time reads/searches only |
| req-grid-history-tt-service | [Service-Layer Historical Projection](#service-layer-historical-projection) | Proposed | Time travel is implemented in TAP services, not by altering ORM default behavior |
| req-grid-history-tt-filter | [Point-In-Time Visibility Filter](#point-in-time-visibility-filter) | Proposed | `created_at`, `updated_at`, and `deleted_at` provide the first-pass visibility rules |
| req-grid-history-tt-reconstruct | [Historical Reconstruction](#historical-reconstruction) | Proposed | Objects updated after the cutoff are reconstructed from history tables |
| req-grid-history-tt-meta | [Historical Response Metadata](#historical-response-metadata) | Proposed | Returned historical objects carry non-persisted `tap_meta.historical` metadata |
| req-grid-history-tt-write | [Write Blocking During Time Travel](#write-blocking-during-time-travel) | Proposed | Historical modes are read-only in v1 |

## Explanation

Time travel is not a second ORM. It is a service-layer mode that projects the graph at a transaction-time cutoff. The caller provides `timetravel_as_of`, and TAP returns the world exactly as it existed at that point in time.

The first implementation is intentionally strict:

- one point in time, not a range
- exact historical world, not ghosted/future annotations
- read/search only, not mutation

This narrow contract keeps the semantics clean while still supporting the future slider/dial experience.

### Time-Travel Scope
----
RID: `req-grid-history-tt-scope`

Status: `Proposed`

The first time-travel implementation supports strict point-in-time historical projection only.

#### Status Details
Proposed as the bounded first pass. This requirement explicitly excludes more ambiguous or UI-heavy temporal modes until point-in-time reconstruction is solid.

#### Implementation
The first implementation supports:

1. Historical read of a single object as of a timestamp.
2. Historical search/traversal of graph objects as of a timestamp.
3. Exact point-in-time state only.

The first implementation does not yet support:

1. Time ranges such as "all changes between A and B".
2. Directional semantics such as favoring prior or next versions.
3. Ghosted future/past objects in the same result set.
4. Replay animation or transition summaries.

#### Development
Removing directional and range semantics from v1 keeps "what is the world at time T?" unambiguous.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-tt-scope-1 | Point-In-Time Only | Proposed | Time travel accepts a single `as_of` timestamp and returns the world at that point in transaction time. | |
| req-grid-history-tt-scope-2 | No Range Semantics In V1 | Proposed | The first implementation does not require querying or merging over time ranges. | |
| req-grid-history-tt-scope-3 | No Directional Semantics In V1 | Proposed | The first implementation does not require a direction parameter for historical projection. | Future candidate for UI/range modes |

#### Future
Range-based historical inspection, directional scrubbing modes, and ghosted annotations should be treated as later capabilities layered on top of strict point-in-time projection.

### Service-Layer Historical Projection
----
RID: `req-grid-history-tt-service`

Status: `Proposed`

Time travel is implemented in TAP's service layer rather than by redefining default ORM behavior.

#### Status Details
Proposed as a key architectural rule. Time travel affects graph semantics, tombstones, edge validity, and response metadata, which makes it a service concern rather than a pure storage abstraction.

#### Implementation
The required service-layer behavior is:

1. Historical reads/searches accept `timetravel_as_of`.
2. Service methods decide whether the canonical row is sufficient or whether historical reconstruction is required.
3. Services query history tables through TAP-owned adapters rather than scattering direct backend calls through unrelated code.
4. Default ORM/model queries remain current-state oriented unless explicitly wrapped by the time-travel service path.

#### Development
This keeps current-state ORM behavior predictable while isolating historical weirdness in one explicit place.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-tt-service-1 | Explicit Historical Service Path | Proposed | Time-travel queries are executed through TAP services rather than implicit ORM-level table swapping. | |
| req-grid-history-tt-service-2 | History Backend Access Is Wrapped | Proposed | Service-layer historical projection uses TAP history adapters/services rather than backend-specific calls at every call site. | |
| req-grid-history-tt-service-3 | Current ORM Remains Current-State | Proposed | Ordinary ORM reads continue to mean current canonical state unless an explicit historical service mode is used. | |

#### Future
If historical query patterns stabilize, TAP may later add higher-level helpers on top of the service layer, but not at the cost of obscuring current-vs-historical semantics.

### Point-In-Time Visibility Filter
----
RID: `req-grid-history-tt-filter`

Status: `Proposed`

Time-travel reads and searches use canonical lifecycle timestamps as a first-pass visibility filter before falling back to historical reconstruction.

#### Status Details
Proposed as the primary optimization strategy for point-in-time projection.

#### Implementation
For a requested `as_of` timestamp:

1. If `created_at > as_of`, the object did not yet exist and must not be returned.
2. If `deleted_at IS NOT NULL` and `deleted_at <= as_of`, the object no longer existed and must not be returned.
3. If `updated_at <= as_of`, the current canonical row is already the correct state and may be returned directly.
4. If `updated_at > as_of`, the correct state must be reconstructed from history.

These timestamp checks should be available on both the entity spine and the BaseModel tables as denormalized lifecycle metadata owned by the service layer.

#### Development
This avoids unnecessary history lookups for objects whose current canonical row already matches the requested time slice.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-tt-filter-1 | Created After Cutoff Excluded | Proposed | Objects with `created_at > as_of` are excluded from point-in-time results. | |
| req-grid-history-tt-filter-2 | Deleted At Or Before Cutoff Excluded | Proposed | Objects with `deleted_at <= as_of` are excluded from strict point-in-time results. | |
| req-grid-history-tt-filter-3 | Canonical Fast Path | Proposed | Objects with `updated_at <= as_of` may be returned from canonical tables without history reconstruction. | |
| req-grid-history-tt-filter-4 | Historical Lookup Trigger | Proposed | Objects with `updated_at > as_of` are routed to history reconstruction. | |

#### Future
If the optimization heuristics become more complex, TAP may later materialize additional historical indexing aids without changing the visibility contract.

### Historical Reconstruction
----
RID: `req-grid-history-tt-reconstruct`

Status: `Proposed`

When canonical timestamps indicate that the current row is newer than the requested historical point, TAP reconstructs the object from the latest history version at or before the cutoff.

#### Status Details
Proposed as the core reconstruction rule for strict point-in-time time travel.

#### Implementation
The reconstruction rule is:

1. Find the latest historical version of the object with history timestamp `<= as_of`.
2. Use that version as the object's returned state.
3. If no qualifying historical version exists, the object is not visible for that historical query.
4. Deletion/tombstone remains part of lifecycle history but does not itself create a visible object after `deleted_at`.

For graph reads:

1. Nodes and edges are reconstructed symmetrically.
2. An edge must not be returned unless the edge itself is visible at `as_of` and both endpoint nodes are also valid for that same point in time.

#### Development
This is the strict "world as it existed then" rule. It deliberately avoids any next-version/previous-version ambiguity in v1.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-tt-reconstruct-1 | Latest At Or Before Cutoff | Proposed | Historical reconstruction uses the latest qualifying history version at or before `as_of`. | |
| req-grid-history-tt-reconstruct-2 | Missing Historical Version Means Not Visible | Proposed | If no qualifying historical version exists, the object is omitted from that historical result set. | |
| req-grid-history-tt-reconstruct-3 | Edge Endpoint Validation | Proposed | Historical edge reconstruction includes a sanity check that both endpoint nodes are valid at the requested point in time. | |

#### Future
Future modes may add "show nearest next version" or "show all versions in range" semantics, but those should be additive to this strict reconstruction rule.

### Historical Response Metadata
----
RID: `req-grid-history-tt-meta`

Status: `Proposed`

Returned historical objects should be marked as historical in response metadata rather than by mutating persisted model fields.

#### Status Details
Proposed as the simplest honest way to distinguish historical projection from current canonical rows.

#### Implementation
The first response-metadata contract is:

```json
{
  "tap_meta": {
    "historical": true
  }
}
```

Rules:

1. `tap_meta.historical` is response metadata, not a persisted database field.
2. Current-state reads may omit the field or return `false`.
3. Additional historical metadata may be added later as needed.

#### Development
This keeps the database clean while still telling callers that the object they received is a historical projection rather than the live canonical row.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-tt-meta-1 | Historical Boolean Exists | Proposed | Historical service responses include `tap_meta.historical` for projected historical objects. | |
| req-grid-history-tt-meta-2 | Metadata Not Persisted | Proposed | Historical markers are injected into response objects/envelopes rather than stored on canonical rows. | |
| req-grid-history-tt-meta-3 | Extensible Metadata Surface | Proposed | The metadata contract allows additional historical fields to be added later without redefining the storage model. | |

#### Future
Likely later additions include `as_of`, source version timestamp, or visibility-mode hints once caller needs become clearer.

### Write Blocking During Time Travel
----
RID: `req-grid-history-tt-write`

Status: `Proposed`

Time-travel mode is read-only in the first implementation.

#### Status Details
Proposed to keep temporal semantics clear while the system is still proving point-in-time reads.

#### Implementation
The required behavior is:

1. Historical read/search service paths accept `timetravel_as_of`.
2. Historical write operations are blocked in v1.
3. A caller must return to current-state mode before performing normal writes.

#### Development
This keeps the first pass focused on reconstruction and avoids prematurely defining "write into the past" semantics that could become very expensive or confusing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-history-tt-write-1 | Read-Only Historical Mode | Proposed | Time-travel service mode supports reads/searches but not writes in v1. | |
| req-grid-history-tt-write-2 | Current-State Required For Mutation | Proposed | Normal writes are performed only in current-state mode unless a future requirement explicitly expands historical-write semantics. | |

#### Future
If TAP ever needs branch-style what-if editing or historical replay mutation, that should be designed as a separate capability rather than casually added to point-in-time reads.
