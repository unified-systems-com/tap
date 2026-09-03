# Grid Search Specification

## Philosophy

Search objects are reusable query definitions stored on the grid as first-class entities. They allow panels and other capabilities to reference a stable search definition instead of embedding ad hoc query logic throughout the system.

A Search must be expressive enough to retrieve useful graph-native data, but narrow enough that execution remains understandable, deterministic, and safe. In v1, that means a small set of execution modes, one-hop traversal only, deterministic ordering, and execution exclusively through the service layer.

Searches always return a graph-shaped result envelope. Even when a consumer is primarily interested in nodes or primarily interested in edges, the result is still represented as `nodes` plus `edges`. That keeps the output compatible with future chaining, composition, and graph-native consumers.

## Goals

|    |                  |                                                                                                      |
| :---: | ---           | ---                                                                                                  |
| 1. | Reusable          | Store search definitions once and reference them from panels and other capabilities                  |
| 2. | Safe              | Restrict execution to read-only, service-layer-controlled access against TAP-managed models          |
| 3. | Graph-Native      | Return results as graph data (`nodes` and `edges`) rather than forcing a flat tabular contract      |
| 4. | Extensible        | Support multiple execution modes without hard-coding all query logic into one implementation         |
| 5. | Deterministic     | Require stable ordering and explicit pagination behavior so repeated execution is predictable         |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-search-obj | [Search Objects](#search-objects) | Implemented | Search is a first-class grid entity with reusable query metadata |
| req-grid-search-exec | [Search Execution](#search-execution) | Implemented | Searches execute through a shared service layer only |
| req-grid-search-module | [Module Search Mode](#module-search-mode) | Implemented | Code-backed searches resolve a registered module runner via `ScopedRegistry` |
| req-grid-search-orm | [ORM Search Mode](#orm-search-mode) | Implemented | Declarative ORM DSL with one-hop traversal and deterministic ordering |
| req-grid-search-results | [Search Results](#search-results) | Implemented | Searches always return the canonical 4-key graph envelope (`nodes`, `edges`, `info`, `warnings`) |
| req-grid-search-canonical-read | [Canonical Read Interface — Break-Glass Discipline](#canonical-read-interface--break-glass-discipline) | Proposed | Gryphon/Search is the canonical graph read interface; raw-ORM graph reads and bespoke-module-as-Gryphon-substitute are break-glass; the urge to use them is a demand signal to extend Gryphon |
| req-grid-search-readonly.sec | [Search Read-Only Execution](#search-read-only-execution) | Implemented | Security requirement enforcing that searches cannot mutate TAP data |
| req-grid-search-readonly-role.sec | [Search Read-Only Least-Privilege Role](#search-read-only-least-privilege-role) | Implemented | The read-only search connection authenticates as a dedicated DB role granted `SELECT` on only the searchable + spine tables; a defense-in-depth backstop so a resolver-guard miss fails closed at the database |
| req-grid-search-authz.sec | [Search Authorization](#search-authorization) | Backlog | Deferred security requirement for search-specific authorization and access controls |

---

### Search Objects
----
RID: `req-grid-search-obj`

Status: `Implemented`

A Search object is the backing entity for a reusable TAP query. It stores the query definition, parameter schema, return preferences, and pagination configuration needed for execution through the TAP service layer.

Canonical entity instance metadata terminology is governed by `req-grid-entity-metadata` in `spec-grid-entity.md`.
Current Search implementation still uses `title` as a field name, but that should be read here as current implementation terminology rather than the preferred long-term canonical instance metadata term.

#### Fields

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| `title` | CharField | Yes | Current implementation field for the search's human-readable name. Canonical entity metadata terminology is `name` per `req-grid-entity-metadata`. |
| `description` | TextField | No | What the search is intended to retrieve |
| `search_type` | CharField | Yes | Execution mode. In v1: `module`, `orm`, or `traversal` |
| `root` | CharField | Yes | Search root. In v1: `node` or `edge` |
| `definition` | JSONField | Yes | Execution-mode-specific search definition |
| `input_schema` | JSONField | No | JSON Schema for domain-specific execution inputs (e.g. a `character_id` parameter). Not used for pagination — `limit` and `offset` are separate execution kwargs. |
| `returns` | JSONField | No | Result preference object controlling primary side, included graph members, and projections |
| `default_limit` | IntegerField | No | Default page size for this search. Null means unpaginated by default. |
| `max_limit` | IntegerField | No | Maximum page size enforced at execution time. Null means uncapped. |

#### Status Details
`Search` model implemented in `tap_grid/models.py` with all fields, `FIELD_VALIDATION_SCHEMA` validation, and cross-field `validate()` hook. Migration `0007_search.py` applied. Tests in `tap_grid/tests/test_search_model.py`.

#### Implementation
A Search is a TAP-managed model derived from `BaseModel`, and therefore hangs off the entity spine like other first-class grid objects.

`search_type` determines how `definition` is interpreted:
- `module` uses a registered search runner key.
- `orm` uses a declarative ORM DSL.
- `traversal` uses TAP traversal language text stored in `definition["query"]` (str or list[str]). See `spec-grid-traversal*.md` for the language and execution specs.

`root` identifies whether the search begins from nodes or edges:
- `node`
- `edge`

`input_schema` is JSON Schema. When present, execution inputs are validated against it before any search runner or ORM logic is invoked.

`returns` is a preference object, not an arbitrary output-shape contract. Search results are always returned in a graph envelope, but `returns` can specify:
- `primary`: `nodes` or `edges`
- `include`: `nodes`, `edges`, or `both`
- optional field projections for `nodes` and `edges`

`default_limit` and `max_limit` are typed integer fields on the model rather than a JSON blob. When a caller provides `limit` or `offset` at execution time, the service layer clamps `limit` to `max_limit` if it is set.

Cross-field invariants on `search_type`, `root`, and `definition` are enforced via the whole-record `validate()` hook (see `req-grid-entity-validation`). For example, a `module` definition that contains unrecognized extra fields raises `ValidationError` at save time.

#### Development
Keep the object surface small. Mode-specific complexity belongs inside `definition`, not in a large set of top-level fields that only apply to one execution mode.

Do not treat `title` as the preferred long-term metadata term for entity instances. Search currently uses `title` in implementation, but higher-level and future specs should align to the canonical metadata terminology defined in `req-grid-entity-metadata`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-obj-1 | Search Is First-Class Entity | Implemented | Search is represented by its own TAP-managed model derived from `BaseModel`. | |
| req-grid-search-obj-2 | Canonical Search Type Field | Implemented | Search stores `search_type` and supports `module`, `orm`, and `traversal` in v1. | |
| req-grid-search-obj-3 | Canonical Root Field | Implemented | Search stores `root` and supports `node` and `edge` in v1. | |
| req-grid-search-obj-4 | Definition Stored as JSON | Implemented | Search stores execution-specific query definition in `definition`. | |
| req-grid-search-obj-5 | Input Schema Uses JSON Schema | Implemented | When `input_schema` is present, execution inputs are validated against it before search execution. | |
| req-grid-search-obj-5-2 | Schema Defaults Fill Absent Inputs | Implemented | A top-level `input_schema` property that declares a JSON Schema `default` supplies that value when the caller omits the input; a caller-supplied value is never overridden, and the defaulted inputs are validated like any other. | 2026-09-02: lets a search that names `$repo` run from a page opened without a query string (the git-serious machinery landing). Top-level properties only. `tap_grid/tests/test_search_model.py`. |
| req-grid-search-obj-6 | Returns Is Preference Object | Implemented | `returns` controls primary side, included graph members, and projections, but does not replace the canonical graph result envelope. | |
| req-grid-search-obj-7 | Pagination Fields Are Typed | Implemented | Search stores pagination defaults in typed `default_limit` and `max_limit` IntegerFields (not a JSON blob). `null` means unpaginated / uncapped. | |
| req-grid-search-obj-8 | Module Definition Is Constrained | Implemented | For `search_type="module"`, v1 `definition` supports only a fully-qualified `runner_key`. | |
| req-grid-search-obj-9 | Cross-Field Validation via validate() | Implemented | `search_type`-specific `definition` constraints (e.g. required fields, disallowed extra fields) are enforced in the whole-record `validate()` hook. | |

#### Future
Consider supporting inline code stored directly on the Search node. This requires a separate execution-safety design and is explicitly deferred.

Consider extending `returns` with richer projection / formatting controls once panel and API consumers establish a concrete need.

---

### Search Execution
----
RID: `req-grid-search-exec`

Status: `Implemented`

All searches execute through a shared TAP service-layer entry point. Consumers such as panels, pages, APIs, and future chained searches do not execute search logic directly.

#### Status Details
Service layer implemented in `tap_grid/search_service.py`. `execute_search()` handles input validation, limit clamping, dispatch to mode executors (stubs for orm/module until Phases 4–5), envelope normalization, and info/warnings population.

#### Implementation
Search execution is service-layer only.

The shared service layer is responsible for:
- loading the Search object
- validating execution inputs against `input_schema`
- dispatching to the correct execution mode
- resolving `module` runners from `definition.runner_key`
- validating that execution returns one of the canonical result envelopes
- enforcing deterministic ordering
- applying pagination behavior
- returning the canonical graph-shaped result envelope

Search scope is limited to TAP-managed models derived from `BaseModel`. Searches do not read arbitrary Django application tables.

Read-only execution requirements are specified in `req-grid-search-readonly.sec`.

Consumers call the service layer by reference to a Search object or Search identifier. They do not bypass it and invoke module runners or ORM definitions directly.

For `module` searches:
- `input_schema` validation occurs before runner dispatch
- the service layer resolves the runner from the persisted `definition.runner_key`
- the service layer validates the returned result envelope before returning it to callers

#### Development
This requirement exists so there is exactly one place to add future enforcement for authorization, rate limiting, pagination caps, observability, and execution controls.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-exec-1 | Service Layer Only | Implemented | Search execution is exposed through a shared TAP service-layer entry point. | |
| req-grid-search-exec-2 | Inputs Validated First | Implemented | Execution inputs are validated against `input_schema` before search logic runs. | |
| req-grid-search-exec-3 | TAP Model Scope Only | Implemented | Search execution is limited to TAP-managed models derived from `BaseModel`. | Excludes unrelated Django tables. |
| req-grid-search-exec-4 | Deterministic Ordering Required | Implemented | Search execution applies deterministic ordering before pagination or result return. | |
| req-grid-search-exec-5 | Canonical Result Envelope | Implemented | Search execution returns the canonical graph-shaped result envelope for every mode. | |
| req-grid-search-exec-6 | Module Runner Resolved From Definition Key | Implemented | For `search_type="module"`, execution resolves the runner from persisted `definition.runner_key`. | |
| req-grid-search-exec-7 | Runner Result Structure Validated | Implemented | Service-layer execution validates that module runner output matches one of the canonical result envelopes before returning it. | |

#### Future
Add service-layer enforcement for maximum page size once operational experience identifies the right cap.

Add search execution metrics, timing, and failure instrumentation.

---

### Search Read-Only Execution
----
RID: `req-grid-search-readonly.sec`

Status: `Implemented`

Search execution is a security-sensitive surface and must be enforced as read-only. Searches must not mutate TAP data, create records, update records, delete records, or trigger side effects that change persisted application state.

#### Status Details
This requirement separates read-only enforcement from general execution flow so the search security model is explicit and can be referenced independently by execution modes and future authorization work.

#### Implementation
All search modes execute under a read-only contract, enforced by a read-only database connection.

The service layer opens a read-only database connection for all search execution. This prevents writes at the database level rather than relying on author convention or code review. ORM searches compile to queries that run over this connection. Module runners also receive execution context bound to the read-only connection.

This means:
- searches do not create, update, or delete TAP-managed records
- searches do not mutate edge properties, entity properties, or other persisted model fields
- module runners execute under the same read-only connection constraint as declarative search modes
- future execution modes must satisfy this requirement before they are considered valid

This requirement is independent of authorization. A caller being authorized to execute a search does not grant permission to mutate data through search execution.

**Prevention and detection.** The read-only connection *prevents* the write (PostgreSQL rejects it — `ReadOnlySqlTransaction`, SQLSTATE `25006`). On its own that rejection is silent: it surfaces as a generic query error, indistinguishable from a malformed query, so a write attempt on the traversal surface — a should-never-happen event, and the signature of either a core executor defect or an injection that escaped bind-parameter safety — would be prevented but never alerted on in production. A `connection.execute_wrapper` on the `search_readonly` alias (`tap_grid/search_readonly_guard.py`, wired on `connection_created`) closes that gap: on a 25006 rejection it emits a `security` Flaw (`invariant_id=search_readonly_write_blocked`, `handling=abort_operation`, blame class by offending callsite) before re-raising. The write stays blocked; the block is now loud. Because it sits at the connection layer, it covers every entry path — `execute_search`'s orm/gryphon/module lanes and direct `execute_gryphon_raw` callers alike.

#### Development
Keeping read-only enforcement as its own security requirement makes it easier to reason about future SQL mode, inline code mode, and authorization work without burying core safety guarantees inside general execution prose.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-readonly.sec-1 | Searches Are Read Only | Implemented | Search execution must not mutate persisted TAP data. | |
| req-grid-search-readonly.sec-2 | Enforced Via Read-Only DB Connection | Implemented | The service layer opens a read-only database connection for all search execution. Writes are rejected at the database level, not just by convention. | |
| req-grid-search-readonly.sec-3 | Module Runners Use Read-Only Connection | Implemented | `module` search runners execute over the same read-only connection. They cannot bypass it via a separate Django connection. | |
| req-grid-search-readonly.sec-4 | Requirement Applies To Future Modes | Implemented | Any future search execution mode must satisfy the read-only requirement before adoption. | |
| req-grid-search-readonly.sec-5 | Separate From Authorization | Implemented | Read-only enforcement is required even when the caller is otherwise authorized to execute the search. | |
| req-grid-search-readonly.sec-6 | Write Attempt Is Detected, Not Only Prevented | Implemented | A write reaching the read-only search connection emits a `security` Flaw (`search_readonly_write_blocked`) — the response-triggering alert — before the DB rejection propagates. Prevention without detection is silent; the guard sits at the connection layer so it covers every execution lane. | `tap_grid/search_readonly_guard.py`; test `tap_grid/tests/test_search_readonly_guard.py`. |

#### Future
Define concrete enforcement mechanisms for each execution mode, especially for future SQL-backed and inline-code search execution.

---

### Search Read-Only Least-Privilege Role
----
RID: `req-grid-search-readonly-role.sec`

Status: `Implemented`
Tags: `Security`

`req-grid-search-readonly.sec` makes the search connection read-only at the *session* level
(`default_transaction_read_only=on`), which blocks writes but says nothing about *which
tables* it may read — today it reuses the application's full database role, so it can
`SELECT` any table in the database. This requirement narrows *read* scope at the database
level: the `search_readonly` connection authenticates as a dedicated least-privilege role
granted `SELECT` on only the Gryphon-searchable tables plus the grid spine.

#### Status Details
This is the database-level (Layer 3) member of the searchability defense-in-depth set. It
is independent of the in-code guards (`req-grid-traversal-exec-searchable.sec`,
`req-grid-traversal-lang-relation-guard.sec`): even if one of those has a gap, a read that
reaches a non-searchable table is denied by PostgreSQL rather than executed. It mirrors the
PostGraphile precedent (the database GRANTs *are* the query surface).

#### Implementation

- The `search_readonly` DB alias authenticates as a dedicated role (e.g. `tap_gryphon_ro`),
  not the application's full role.
- The role holds `SELECT` on exactly: the tables of every `GRYPHON_SEARCHABLE` model
  (`req-grid-traversal-exec-searchable.sec`) plus the spine tables the executor always reads
  (`tap_entity`, `tap_edge`, `tap_entity_type`, `tap_dimension`). It holds no other table
  privileges and no write privileges.
- The role and its grants are provisioned at boot, after migrations settle, by
  `req-boot-search-role` — the grant set is derived from the searchable registry so it can
  never silently drift from the code, and it fails safe (a table not yet granted is simply
  unreadable).
- A read that the role is not granted fails with PostgreSQL `permission denied`
  (SQLSTATE 42501); that rejection is made loud by `req-grid-db-permission-flaw.sec` — a
  42501 on this connection is the tripwire that an in-code guard leaked.
- **Validation loop:** the Gridkin SQL snapshots enumerate every table Gryphon touches; a
  guard asserts that set is a subset of the granted set, so a searchable model whose executor
  path reaches an ungranted table is caught in CI, not in production.
- **The role also carries the resource contract.** The same `ALTER ROLE` provisioning pins
  the resource-bound GUCs (`statement_timeout`, `lock_timeout`, `temp_file_limit`, a
  conservative `work_mem`) per `req-grid-traversal-exec-resource-bounds.sec`, so one role
  carries both the least-privilege *read scope* (grants) and the resource *bounds* (GUCs),
  inherited automatically by every connection that authenticates as it.

**Landed vs. deferred in v0 (honest scope).** The role, its model-layer-derived `SELECT` grants,
the resource-GUC pinning, and the 42501 detection tie-in are **built** (`tap_grid/search_role.py`,
provisioned at boot; sec-1/2/3/4/6 `Implemented`). Two design points are not yet realized:
(a) the grant set is derived from the **grid-table classification** (`GRID_TABLE_ROLE`, one
declaration per model, derived through `tap_grid/grid_tables.py` — the shared single source of
truth also consumed by the ORM read backstop; `req-grid-table-classification.sec` in
`spec-grid-security.md`), not a narrower `GRYPHON_SEARCHABLE` subset, because the opt-in searchability gate
(`req-grid-traversal-exec-searchable.sec`) is `Proposed` — "searchable" ≡ "every registered
grid type" until it lands (broader than the target, still strictly grid-only); (b) the
**Validation loop** above — the CI guard asserting Gridkin's touched-table set is a subset of
the grant (sec-5) — is `Proposed`, not built. The authentic SET-ROLE test proves the grants
directly meanwhile.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-readonly-role.sec-1 | Dedicated Role, Not App Role | Implemented | The `search_readonly` connection authenticates as a dedicated least-privilege DB role, not the application's full database role. | |
| req-grid-search-readonly-role.sec-2 | Grants Limited To Searchable + Spine | Implemented | The role holds `SELECT` on only the `GRYPHON_SEARCHABLE` model tables plus the grid spine tables, and no other tables and no writes. | |
| req-grid-search-readonly-role.sec-3 | Grants Derived, Not Hand-Maintained | Implemented | The grant set is computed from the grid-table classification at provision time (`tap_grid/grid_tables.py`, shared with the ORM read backstop — `req-grid-table-classification.sec`), so it cannot drift from the models and a new un-granted table fails safe (unreadable). | Derivation contract owned by `req-grid-table-classification.sec`. |
| req-grid-search-readonly-role.sec-4 | Independent Of In-Code Guards | Implemented | The DB grant is a standalone layer: a read reaching a non-searchable table is denied by PostgreSQL even if the in-code searchability/relation guards missed it. | Defense in depth. |
| req-grid-search-readonly-role.sec-5 | Touched Tables Are A Subset Of Granted | Proposed | A CI guard asserts the set of tables Gryphon's SQL touches (from Gridkin snapshots) is a subset of the granted set. | Catches under-grant before production. |
| req-grid-search-readonly-role.sec-6 | Role Pins The Resource GUCs | Implemented | The same provisioning pins `statement_timeout`, `lock_timeout`, `temp_file_limit`, and a conservative `work_mem` on the role, so the resource bounds of `req-grid-traversal-exec-resource-bounds.sec` are inherited by every search connection without per-query code. | One role, both scope and bounds. |

#### Future
- Column-level grants and/or secure views (projecting/masking specific columns of a searchable
  model) are a later refinement; v0 is table-level `SELECT`.
- **Row-Level Security for dimension / entity scoping.** The row-level analog of this
  requirement's table-level grant. When per-dimension/per-entity read (and write) down-scoping
  is built — today an accepted-deferred edge in `spec-security-posture.md`, where `grid.read`
  is grid-wide — PostgreSQL RLS policies on `tap_entity` / `tap_edge`, keyed on a
  per-transaction session GUC set from `CallerContext`, are the DB-layer backstop beneath the
  app-layer filter (`USING` for read visibility, `WITH CHECK` for writes; one mechanism for
  both). Build-time edges: `FORCE ROW LEVEL SECURITY` (owner bypass), per-transaction GUC
  set/reset (connection-pooler scope leak), `LEAKPROOF`/leaky-operator side-channels. Deferred
  *with* the dimension-scoping work, not before it.

---

### Module Search Mode
----
RID: `req-grid-search-module`

Status: `Implemented`

`module` search mode resolves a registered search runner and delegates execution to that runner through a TAP registry-backed abstraction.

#### Status Details
This requirement formalizes code-backed search behavior without storing executable code directly on the Search object.

#### Implementation
A `module` search stores exactly one module-specific field in `definition`: `runner_key`.

`definition` shape in v1:

```json
{
  "runner_key": "tap_plugins.grid_fixtures.searches:node-neighbors"
}
```

Persisted `runner_key` values must be fully qualified in `scope:key` format.
Short keys are not allowed in stored Search definitions.
No additional module-specific definition fields are supported in v1.

Complete example:

```json
{
  "search_type": "module",
  "root": "node",
  "definition": {
    "runner_key": "tap_plugins.grid_fixtures.searches:node-neighbors"
  }
}
```

Module search runners are resolved through a first-class `ScopedRegistry`, following the registry patterns defined in `spec-grid-registry.md`.

The registry contract is:
- each runner registers under a scoped key
- duplicate registration of the same scoped key is a configuration error
- persisted searches store fully-qualified keys so runtime lookup is exact and unambiguous

In v1, module runners are plain callables.

The callable contract is:
- receives the Search object
- receives validated execution inputs
- returns one of the canonical search result envelopes

Canonical full result envelope:

```json
{
  "nodes": [...],
  "edges": [...]
}
```

Canonical paginated result envelope:

```json
{
  "count": 0,
  "limit": 25,
  "offset": 0,
  "results": {
    "nodes": [...],
    "edges": [...]
  }
}
```

Module runners execute through the search service layer. They do not bypass service-layer validation or future authorization enforcement.

Failure behavior:
- invalid `module` `definition` is a validation failure
- unresolved `runner_key` is an execution failure
- duplicate runner registration is a configuration failure
- invalid runner result envelope is an execution failure

Recommended exception names for later implementation:
- `InvalidSearchDefinitionError`
- `SearchRunnerNotFoundError`
- `SearchExecutionError`

#### Development
Module mode is the intentionally flexible option for searches that do not fit the declarative ORM DSL. It should remain explicit and registry-backed rather than resolving arbitrary import paths from entity data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-module-1 | Runner Key Required | Implemented | `module` searches require `definition.runner_key`. | |
| req-grid-search-module-2 | Runner Key Fully Qualified | Implemented | Stored `runner_key` values must use fully-qualified `scope:key` format. | |
| req-grid-search-module-3 | Scoped Registry Resolution | Implemented | Module search runners are resolved through a `ScopedRegistry`. | |
| req-grid-search-module-4 | Duplicate Scoped Key Fails | Implemented | Duplicate registration of the same scoped runner key is a configuration error. | |
| req-grid-search-module-5 | Runner Receives Search And Inputs | Implemented | In v1, module runners are plain callables that receive the Search object and validated execution inputs. | |
| req-grid-search-module-6 | Runner Returns Canonical Result Envelope | Implemented | Module runners return one of the canonical full or paginated graph result envelopes. | |
| req-grid-search-module-7 | No Extra Definition Fields In V1 | Implemented | V1 `module` definitions support only `runner_key` and reject additional module-specific fields. | |

#### Future
Consider adding registry inspection and health checks for registered search runners.

---

### ORM Search Mode
----
RID: `req-grid-search-orm`

Status: `Implemented`

`orm` search mode uses a declarative JSON DSL that compiles to read-only TAP ORM queries. The v1 DSL is intentionally narrow: root selection, conjunctive filters, deterministic ordering, optional pagination, and at most one graph hop.

#### Status Details
This requirement defines the smallest ORM DSL that can support useful graph-native searches without drifting into an ad hoc traversal language.

#### Implementation
An `orm` search stores its query in `definition`.

Example shape:

```json
{
  "filters": {
    "entity_type": "character"
  },
  "hops": [
    {
      "direction": "out",
      "edge_type": "WIELDS_ARTIFACT",
      "target_filters": {
        "entity_type": "artifact"
      }
    }
  ],
  "order_by": ["created_at"]
}
```

Filter keys follow Django ORM double-underscore traversal syntax. Fields on the typed model are referenced directly (`"summary": "security"`). Fields on the Entity spine are referenced via `entity__` prefix (`"entity__entity_type": "character"`, `"entity__created_at__gte": "2025-01-01"`). This mirrors the natural Django ORM join path and requires no additional mapping layer.

V1 ORM definition supports:
- root type selected by Search `root` (`node` or `edge`)
- conjunctive root `filters` using Django `__` traversal syntax
- optional `hops` list with at most one hop
- hop `direction`: `out` or `in`
- hop `edge_type`
- hop endpoint filters (`target_filters` / `source_filters`) using the same `__` traversal syntax
- deterministic `order_by`

V1 ORM definition does not support:
- multi-hop traversal
- boolean composition (`OR`, `NOT`, nested logical trees)
- arbitrary joins outside the graph model
- access to non-TAP Django models

One-hop traversal means:
- a `node`-rooted search may inspect edges directly connected to the matched node set
- an `edge`-rooted search may inspect the source or target node set connected to the matched edge set
- traversal does not continue beyond that single relationship boundary

If `order_by` is not provided, execution must fall back to a deterministic default ordering appropriate to the root model.

#### Development
Keep the ORM DSL graph-native and small. If future requirements demand traversal chaining or boolean expression trees, that should be treated as a deliberate expansion, not incrementally smuggled into the v1 structure.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-orm-1 | Definition Stored as JSON DSL | Implemented | `orm` searches store query structure in `definition` as JSON. | |
| req-grid-search-orm-2 | Root Chosen by Search Root Field | Implemented | ORM execution begins from the Search object's `root` value (`node` or `edge`). | |
| req-grid-search-orm-3 | Conjunctive Filters Supported | Implemented | V1 ORM search supports conjunctive filters on the selected root set. | |
| req-grid-search-orm-4 | One Hop Maximum | Implemented | V1 ORM search supports at most one graph hop from the root set. | |
| req-grid-search-orm-5 | Hop Direction Explicit | Implemented | A hop explicitly declares `in` or `out` direction. | |
| req-grid-search-orm-6 | Hop Edge Type Explicit | Implemented | A hop may constrain traversal by `edge_type`. | |
| req-grid-search-orm-7 | Endpoint Filters Supported | Implemented | A hop may apply endpoint filters to the connected node set. | |
| req-grid-search-orm-8 | Non-TAP Models Excluded | Implemented | ORM search definitions cannot target models outside TAP-managed `BaseModel` descendants. | |
| req-grid-search-orm-9 | Deterministic Ordering | Implemented | ORM execution applies explicit or default deterministic ordering before pagination. | |

#### Future
Consider supporting boolean composition (`OR`, `NOT`, nested logical expressions`) once real searches demonstrate the need.

Consider supporting traversal chaining or linked searches as a separate query-composition mechanism rather than expanding v1 hops into an ad hoc graph language.

Consider supporting SQL-backed searches as a separate mode if a narrow, read-only, TAP-scoped execution model can be specified safely.

---

### Search Results
----
RID: `req-grid-search-results`

Status: `Implemented`

Searches always return the canonical 4-key graph envelope. Every execution mode returns the same shape. Hard failures raise a `SearchExecutionError` (not an envelope-level error key) so callers can unambiguously distinguish "search ran and produced warnings" from "search failed to execute at all."

#### Status Details
Result-shape consistency is being specified up front so search consumers can build against one canonical contract regardless of search mode.

#### Implementation
Canonical result envelope:

```json
{
  "nodes": [],
  "edges": [],
  "info": {},
  "warnings": {}
}
```

- `nodes`: list of node objects matched by the search
- `edges`: list of edge objects matched or traversed by the search
- `info`: metadata about the execution — e.g. total count, execution time, applied limit/offset, which filters were active
- `warnings`: non-fatal issues — e.g. a filter referenced a deprecated field, a hop produced no results, applied `max_limit` clamping. Keyed by warning code.

Hard execution failures (unresolved runner key, invalid definition at execution time, database error) raise `SearchExecutionError`. They are never silently folded into the envelope.

When pagination is enabled, the canonical paginated result envelope wraps the inner graph envelope:

```json
{
  "count": 0,
  "limit": 25,
  "offset": 0,
  "results": {
    "nodes": [],
    "edges": [],
    "info": {},
    "warnings": {}
  }
}
```

`limit` and `offset` are passed as execution-time kwargs to the service layer. The service layer clamps `limit` to the Search object's `max_limit` if set and records the clamping in `warnings`. `count` is the total number of primary-side results before pagination.

Node and edge members are serialized as JSON objects. `returns` may narrow which side is primary, which graph members are included, and which fields are projected, but it does not change the top-level envelope shape.

`limit`, `offset`, and `count` apply to the `primary` side declared by `returns.primary`. Graph members included from the non-primary side are incidental connected results and are not independently paginated.

#### Development
The 4-key envelope is a deliberate constraint. `info` and `warnings` as first-class keys prevent consumers from scraping error signals out of opaque metadata and keep the contract explicit across all execution modes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-results-1 | 4-Key Envelope | Implemented | All search results return a JSON object with exactly `nodes`, `edges`, `info`, and `warnings` keys. | |
| req-grid-search-results-2 | Paginated Wrapper | Implemented | Paginated results wrap the 4-key envelope in `count`, `limit`, `offset`, and `results`. | |
| req-grid-search-results-3 | Hard Failures Raise | Implemented | Hard execution failures raise `SearchExecutionError` and are never silently placed in the envelope. | |
| req-grid-search-results-4 | info Contains Execution Metadata | Implemented | `info` contains execution metadata (applied limit/offset, count, timing). Structure TBD at implementation time. | |
| req-grid-search-results-5 | warnings Contains Non-Fatal Issues | Implemented | `warnings` is a dict keyed by warning code. Non-fatal issues (deprecated fields, max_limit clamping) are placed here, not in `info`. | |
| req-grid-search-results-6 | JSON Serialized Members | Implemented | Node and edge members in search results are serialized as JSON objects. | |
| req-grid-search-results-7 | Returns Does Not Replace Envelope | Implemented | `returns` may shape inclusion and projection but does not change the top-level 4-key envelope shape. | |
| req-grid-search-results-8 | Pagination Applies To Primary Side | Implemented | `limit`, `offset`, and `count` apply to the `primary` side declared by `returns.primary`, not to the total number of graph members in the full envelope. | |
| req-grid-search-results-9 | max_limit Clamping Recorded | Implemented | When the service layer clamps caller-provided `limit` to `max_limit`, the clamping is recorded in `warnings`. | |

#### Future
Consider defining standard result projection helpers for common consumers such as table panels, graph views, and form pickers.

---

### Search Authorization
----
RID: `req-grid-search-authz.sec`

Status: `Backlog`

Search-specific authorization and access-control behavior is a required security concern, but it is deferred from the initial search specification.

#### Status Details
Backlog requirement created so search execution does not silently inherit undefined security behavior.

#### Implementation
Future work must define:
- whether searches execute in caller context or a narrower search-specific permission model
- whether different search objects can have different access policies
- whether module runners require additional approval or scope controls
- how search execution interacts with page, panel, and API authorization

#### Development
Security posture for searches must be designed before searches are exposed broadly through user-facing pages, APIs, or plugin ecosystems.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-authz.sec-1 | Security Requirement Exists | Proposed | Search authorization is tracked as a dedicated security requirement. | |
| req-grid-search-authz.sec-2 | Execution Context Undefined by Default | Proposed | Search execution does not claim an implicit authorization model until this requirement is implemented. | |

#### Future
Define caller-context authorization, search object visibility rules, and execution-policy controls.

### Canonical Read Interface — Break-Glass Discipline

RID: `req-grid-search-canonical-read`

Status: `Proposed`

Gryphon and the Search system (the first-class `module` and `orm` modes, all
routed through the service layer over a read-only connection) are the
**canonical** way to read TAP-managed graph data. This requirement does not
deprecate or weaken any existing Search mode — `req-grid-search-module` and
`req-grid-search-orm` remain first-class. It governs the *policy on what to
reach for*, decided 2026-05-19 (George):

- **Raw Django ORM querying of graph models** (`Entity`, `Edge`, `BaseModel`
  subclasses) that bypasses the service layer / Search entirely, and
- **authoring a new bespoke `module` search runner specifically as a
  substitute for a capability Gryphon is missing**,

are **break-glass: a genuine last resort, never a go-to.** Both were
reasonable *before Gryphon*. From here on, the *urge* to reach for either is
to be re-interpreted as a **demand signal to build out whatever Gryphon is
missing**, not a license to bypass it. The gap is the signal; route the energy
upstream so the next caller inherits the capability instead of another
divergent query path. (Structurally the same discipline as the future-seam
rule: an impulse becomes evidence of demand to address at the canonical layer,
not a shortcut.)

**Carve-out — do not misapply.** Direct ORM remains legitimate, and is *not*
break-glass, for: database migrations; intentional low-level / model-level
tests; the service layer's own internals; and the Search `orm`-mode compiler
which legitimately builds ORM queries *on behalf of* the canonical interface.
Break-glass is specifically *application/plugin/collector code reading the
graph by going around Gryphon/Search*.

#### Enforcement (designed here; not yet built)

The principle is in force now via `AGENTS.md` Core TAP Rules and agent
memory; the code-level enforcement is specified here and Proposed because the
two surfaces have very different shapes and one is a genuine mechanism fork:

- **Module-runner registration is a bounded chokepoint.**
  `register_search_runner` (`tap_grid/registry.py`) is a single function. A
  break-glass affordance there is concrete: registering a runner whose purpose
  is to substitute for missing Gryphon capability must be a *deliberate,
  greppable, logged acknowledgement* (an explicit opt-in argument /
  break-glass marker + a loud one-time WARNING naming it break-glass and
  pointing at "extend Gryphon"), not a frictionless default. Low blast
  radius; implementable as a focused change.
- **Raw-ORM-graph-read is diffuse — there is no runtime chokepoint, and a
  runtime guard would be the wrong tool** (it would fight the carve-outs and
  the service layer's own legitimate ORM use). The correct mechanism is
  *static*: a lint rule or a CI gate that flags direct `.objects` / queryset
  access to graph models from application/plugin/collector code outside the
  named carve-outs, treating a hit as the demand signal. This carries a real
  false-positive / carve-out surface, so the specific mechanism (custom `ruff`
  rule vs. a CI grep gate vs. a single sanctioned `break_glass`-marked query
  helper everything-else-is-banned-relative-to) is a deliberate decision to
  settle before implementation rather than guess and sprawl.

#### Recommended Next Step (on pickup — parked 2026-05-19, decision-ready)

Parked deliberately, not abandoned: the principle is in force now via
AGENTS.md/memory; only the mechanical catcher is unbuilt. When picked up, the
recommended 2-track (no re-litigation needed unless the recommendation is
rejected):

1. **Module surface — bounded, do first.** Add a deliberate, greppable,
   logged break-glass opt-in to `register_search_runner`
   (`tap_grid/registry.py`; see also `tap_plugins/base.py` callers). Small,
   single chokepoint, no mechanism fork.
2. **ORM surface — CI baseline-ratchet gate.** Mirror the proven
   `tap/tests/test_log_site_ids.py` scanner pattern: flag direct graph-model
   `.objects`/queryset access in application/plugin/collector code outside the
   already-enumerated carve-outs, baseline-ratcheted so existing violations
   don't block but no new ones land, burn down over time. Reuses an existing
   TAP enforcement idiom; least uninvited sprawl.

The single sanctioned `break_glass`-marked helper (strongest greppability,
most invasive now) stays available as a later upgrade if the ratchet proves
insufficient. No work proceeds here without an explicit pickup decision.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-search-canonical-read-1 | Gryphon/Search Is Canonical | Proposed | Reading TAP-managed graph data is done through Gryphon/Search via the service layer. First-class `module`/`orm` modes are unaffected. | Principle in force via AGENTS.md/memory now. |
| req-grid-search-canonical-read-2 | ORM/Bespoke-Module Are Break-Glass | Proposed | Raw-ORM graph reads bypassing the service layer, and authoring a new bespoke module runner as a Gryphon substitute, are last-resort only. | Never a go-to. |
| req-grid-search-canonical-read-3 | Urge Is A Demand Signal | Proposed | The impulse to reach for either is re-interpreted as a demand signal to extend Gryphon, not a license to bypass it. | The reframe is the point. |
| req-grid-search-canonical-read-4 | Carve-Outs Preserved | Proposed | Migrations, low-level/model tests, service-layer internals, and the Search `orm`-mode compiler are explicitly not break-glass. | Prevents misapplication breaking sanctioned low-level access. |
| req-grid-search-canonical-read-5 | Module Registration Break-Glass Affordance | Proposed | `register_search_runner` gains a deliberate, greppable, logged break-glass opt-in for Gryphon-substitute runners. | Bounded chokepoint; implementable focused. |
| req-grid-search-canonical-read-6 | ORM Static Enforcement Mechanism | Proposed | Raw-ORM-graph-read enforcement is static (lint/CI gate honoring carve-outs), not a runtime guard. Specific mechanism is an open decision before build. | The genuine fork; honest false-positive surface. |

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
