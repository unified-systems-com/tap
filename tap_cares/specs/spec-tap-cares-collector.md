# tap-cares Collector Specification

## Philosophy

Collectors are tap-cares capabilities that gather data from a source and prepare it for TAP-owned processing. The collector system rests on three foundations:

- an on-grid `Collector` node that represents the capability TAP can inspect, schedule, and manage — declared as a dual-existence capability per `tap_grid/specs/spec-grid-dual-existence.md`
- a `collector_registry` that maps the collector node's stable registry key to trusted Python code registered at startup
- a public entry point `run_collection(collector)` that owns the entire execution path: CollectionJob creation, HAS_COLLECTION_JOB linking, task enqueueing, and lifecycle bookkeeping

`run_collection` is the only legal way to start a collection. The scheduler subsystem — now implemented, specified in `tap_cares/specs/spec-tap-cares-scheduler.md` — is the steady-state caller: it decides *when* a collection runs and invokes `run_collection`. The scheduler does not reach behind `run_collection` to create CollectionJobs, manipulate Django Tasks, or coordinate Collector identity. This is the **scheduler boundary**: scheduling is trigger; collection is everything from trigger onward. The scheduler's internals stay in its own spec.

The Administrivia HTMX handler is a permitted direct caller of `run_collection` for human-triggered manual runs, alongside the scheduler's automated invocations. `run_collection`'s contract is identical for both callers.

Status messages and richer event records remain backlog (`req-tap-cares-collector-job-logs`). This spec slice defines the collector model-to-module mapping, the dual-existence registration mechanism, the public `run_collection` entry point, collector self-tests/readiness, the Django Task execution boundary, the approved GRIFT import path for collection results, and the on-grid `CollectionJob` execution record.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | On-Grid      | Represent collector capabilities as TAP-managed grid nodes       |
| 2. | Registered   | Resolve executable collector code through a scoped registry      |
| 3. | Deterministic | Require fully qualified registry keys for persisted collectors  |
| 4. | Safe Shape   | Prevent grid data from becoming an arbitrary code loading path   |
| 5. | Conventional | Follow standard TAP `BaseModel` conventions and model-building skill guidance |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-collector-model | [Collector Model](#collector-model) | Refactoring | On-grid dual-existence capability node; INTERNAL_ONLY |
| req-tap-cares-collector-registry | [Collector Registry](#collector-registry) | Implemented | Scoped registry mapping collector keys to registered runner code |
| req-tap-cares-collector-registration | [Collector Registration](#collector-registration) | Proposed | `register_collector(...)` registers the runner read-only at `ready()`; `reconcile_collector_nodes()` materializes the on-grid Collector node under a bound actor |
| req-tap-cares-collector-concurrency | [Collector Concurrency Policy](#collector-concurrency-policy) | Backlog | Future per-collector maximum simultaneous run count |
| req-tap-cares-collector-module-class | [Collector Module Class](#collector-module-class) | Implemented | Registered collector classes instantiated by tap-cares |
| req-tap-cares-collector-packaging | [Collector Packaging](#collector-packaging) | Refactoring | Each collector is a self-contained `collectors/<name>_collector/` package |
| req-tap-cares-collector-config | [CollectorConfig](#collectorconfig) | Implemented | JSON-safe collector configuration object |
| req-tap-cares-collector-self-test | [Collector Self-Test And Readiness](#collector-self-test-and-readiness) | Approved for Development | Synchronous readiness diagnostic run as collection phase 1; result stored on `CollectionJob.self_test`; `full` vs `self_test_only` run modes; failed self-test = standard failure mode |
| req-tap-cares-collector-run-collection | [Run Collection Entry Point](#run-collection-entry-point) | Proposed | Public callable `run_collection(collector)` owns CollectionJob creation, HAS_COLLECTION_JOB linking, and task enqueueing |
| req-tap-cares-collector-task-execution | [Collector Task Execution](#collector-task-execution) | Refactoring | Django Tasks worker-process execution boundary; tasks fire only via `run_collection` |
| req-tap-cares-collector-read-boundary | [Collector Read Boundary](#collector-read-boundary) | Refactoring | Collector modules read through approved search/read surfaces and only submit result mutations through GRIFT import |
| req-tap-cares-collector-grift-import | [Collector GRIFT Import Surface](#collector-grift-import-surface) | Refactoring | Collector result grid mutations route through the GRIFT importer; batch tracking accumulates on the collector instance |
| req-tap-cares-collector-job-model | [CollectionJob Model](#collectionjob-model) | Refactoring | INTERNAL_ONLY execution record; `results` + `self_test` accumulators; produced batches via `PRODUCED_BATCH` edges |
| req-tap-cares-collector-job-sole-writer | [CollectionJob Sole-Writer Invariant](#collectionjob-sole-writer-invariant) | Proposed | Only `run_collection` and the task body write to CollectionJob; helpers accumulate in-memory |
| req-tap-cares-collector-job-edge | [Collector HAS_COLLECTION_JOB Edge](#collector-has_job-edge) | Implemented | Graph relationship from Collector root node to its CollectionJob nodes |
| req-tap-cares-collector-job-lifecycle | [CollectionJob Lifecycle Status](#collectionjob-lifecycle-status) | Implemented | Job status reflects Django Tasks lifecycle states |
| req-tap-cares-collector-failure-mode | [Collector Failure Mode](#collector-failure-mode) | Proposed | Framework convention for how a collector signals failure; KSI and other collectors follow this protocol rather than re-specifying it |
| req-tap-cares-collector-job-logs | [Collection Job Status Messages And Logs](#collection-job-status-messages-and-logs) | Backlog | Deferred richer in-process status/log/event stream |
| req-tap-cares-collector-strict-isolation | [Strict Collector Isolation](#strict-collector-isolation) | Backlog | Future stronger isolation for untrusted or high-risk collector execution |
| req-tap-cares-collector-runtime-helpers | [Shared Collector Runtime Helpers](#shared-collector-runtime-helpers) | Backlog | Standard helper modules (git, http, archive, …) collectors can compose from |

## Collector Model
----
RID: `req-tap-cares-collector-model`
Status: `Refactoring`

`Collector` is the grid-side representation of a tap-cares collector capability and is the canonical first consumer of the dual-existence pattern (see `tap_grid/specs/spec-grid-dual-existence.md`).

`Collector` must be implemented as a standard TAP-managed `BaseModel` node using the model-building skill at `tap_grid/skills/add-model/SKILL.md`. The model should follow ordinary TAP model conventions rather than re-specifying boilerplate in this requirement. Those conventions include entity-spine backing, `ENTITY_TYPE`, display metadata, `FIELD_CRUD_SCHEMA`, `FIELD_VALIDATION_SCHEMA`, `CREATE_REQUIRED`, `get_name()`, history behavior, and tests for creation, validation, display projection, and dimensions.

`Collector` declares `INTERNAL_ONLY: ClassVar[bool] = True` per `req-grid-entity-internal`. The generic service-layer CRUD verbs and the GRIFT importer cannot create, patch, replace, or delete `Collector` rows. The sole legal creation path is `reconcile_collector_nodes()` (see [Collector Registration](#collector-registration)), which writes through `write_batch(..., _internal_only_bypass=True)` from `tap_grid.services` (the trusted-internal escape hatch over the same pipeline `_create_node_internal` wraps; see `req-grid-service-write-internal-create` in `spec-grid-service-write.md`) to materialize the node while preserving the full write pipeline. `register_collector(...)` itself writes no grid node.

The collector node must not store arbitrary filesystem paths, dynamic import paths, or executable code. It stores a fully qualified registry key. The registry is the controlled intermediary between grid data and executable code.

Collector-specific model requirements:

- `Collector` has a human-readable `name`.
- `Collector` has a plain-text `description`.
- `Collector` has a top-level `collector_registry` field.
- `collector_registry` stores the fully qualified registry key used to resolve the collector's registered runner.
- Persisted `collector_registry` values must use `scope:key` format.
- Persisted collector nodes must not use short keys.
- Persisted `collector_registry` values are unique per grid in v0; two Collector nodes may not share the same registry key while per-instance configuration is deferred.
- The on-grid `entity_id` for a Collector is deterministically derived from its `collector_registry` value: `entity_id = uuid5(NAMESPACE_COLLECTOR, collector_registry)`. The `NAMESPACE_COLLECTOR` UUID is a module-level constant in `tap_cares/registry.py`.
- v0 ships only `name`, `description`, and `collector_registry`. Per-instance configuration is deferred (see [CollectorConfig](#collectorconfig)); the first concrete collector (FedRAMP 20x KSI) hardcodes its behavior in the registered class.
- The v0 default dimension is `{"tap_cares": "collector"}`.
- Instance-derived collector dimensions are deferred until TAP's dimension conventions are revisited.

The scheduler will use `Collector` nodes to determine which collector capability to execute. The scheduler relationship and execution behavior are out of scope for this requirement; see [Run Collection Entry Point](#run-collection-entry-point) for the public callable the scheduler invokes.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-model-1 | Standard BaseModel | Implemented | `Collector` is specified as a normal TAP-managed `BaseModel` node implemented through the model-building skill conventions. | |
| req-tap-cares-collector-model-2 | Registry Field | Implemented | `Collector` has a top-level `collector_registry` field that stores the registered collector runner key. | |
| req-tap-cares-collector-model-3 | Fully Qualified Key | Implemented | `collector_registry` values persisted on Collector nodes must use `scope:key` format. | |
| req-tap-cares-collector-model-4 | No Short Keys | Implemented | Persisted Collector nodes reject short, unscoped registry keys. | |
| req-tap-cares-collector-model-5 | Default Dimension | Implemented | New Collector nodes use the v0 default dimension `{"tap_cares": "collector"}`. | |
| req-tap-cares-collector-model-6 | Dynamic Dimensions Deferred | Implemented | Instance-derived collector dimension values are explicitly deferred. | |
| req-tap-cares-collector-model-7 | Unique Registry Key | Implemented | v0 `collector_registry` values are unique within a grid. Attempts to persist a second Collector with an existing `collector_registry` value fail validation. | Enforced via DB-level `unique=True`; revisit when per-instance configuration exists. |
| req-tap-cares-collector-model-8 | v0 Field Set | Implemented | v0 `Collector` exposes only `name`, `description`, and `collector_registry`. Per-instance configuration fields are deferred. | |
| req-tap-cares-collector-model-9 | INTERNAL_ONLY | Proposed | `Collector.INTERNAL_ONLY = True`. Generic `create_node` / `patch_node` / `replace_node` / `delete_node` and GRIFT import all reject the `collector` entity type. | |
| req-tap-cares-collector-model-10 | Deterministic Entity ID | Proposed | A Collector's `entity_id` is `uuid5(NAMESPACE_COLLECTOR, collector_registry)`. The same `scope:key` always yields the same `entity_id` across reloads and across grids. `scope` is a REQUIRED explicit argument to `register_collector` (conventionally the plugin slug), never inferred from `cls.__module__`: the id is a durable, cross-referenced grid key (the reconcile key for the on-grid Collector node and a hardcoded `SCHEDULED_TARGET` target in schedule grift bundles), so a Python module rename must not silently change it. The package-mode migration proved the module path is mutable; the slug is the stable identity. | `NAMESPACE_COLLECTOR` is a module-level UUID constant in `tap_cares/registry.py`. Guarded by `tap_cares/tests/test_schedule_grift_targets_resolve.py` (every grift `SCHEDULED_TARGET` resolves to a registered collector's derived id). |
| req-tap-cares-collector-model-11 | Reconcile Is Sole Creator | Proposed | The only legal path that creates a `Collector` row is `reconcile_collector_nodes()` (see [Collector Registration](#collector-registration)), which writes through `write_batch(..., _internal_only_bypass=True)` from `tap_grid.services`; `register_collector(...)` writes no grid node. | |

## Collector Registry
----
RID: `req-tap-cares-collector-registry`
Status: `Implemented`

The collector registry is the controlled mapping from on-grid collector definitions to executable collector code.

The registry should be named `collector_registry` and modeled on the search system's module-runner registry. It should use TAP's standard `ScopedRegistry` pattern so independently authored apps and plugins can register collector runners under local names without colliding.

Registry key format:

```text
scope:key
```

Example:

```text
plugins.fedramp_20x_ksi.collectors:ksi-catalog
```

The scope identifies where the runner was registered from, typically the module path of the registering callable. The key identifies the runner within that scope.

Collector runners are registered by trusted app or plugin code at startup. A `Collector` node never causes TAP to import a module, read a filesystem path, evaluate code, or otherwise load code dynamically from grid data. At execution time, TAP resolves the persisted `collector_registry` value by looking it up in `collector_registry`.

The collector registry is separate from `search_runner_registry`. Search runners and collector runners have different contracts and should not share a registry, even if both use the same underlying `ScopedRegistry` abstraction.

The registry instance and its public helpers live in `tap_cares/registry.py`, mirroring the search precedent in `tap_grid/registry.py`:

```python
collector_registry: ScopedRegistry[type[CollectorBase]] = ScopedRegistry(
    "collector",
    validate_key=_validate_collector_key,
    validate_scope=_validate_collector_key,
)

def register_collector(
    key: str, cls: type[CollectorBase], *, name: str, description: str, scope: str | None = None
) -> None: ...
def reconcile_collector_nodes() -> dict[str, int]: ...
def get_collector(collector_key: str) -> type[CollectorBase]: ...
```

`register_collector` and `get_collector` are the public plugin surface; `reconcile_collector_nodes()` is the public materialization surface (called by boot, not plugins). Plugin code should call the helpers rather than the registry instance directly so the type narrowing and `CollectorBase` subclass check ([req-tap-cares-collector-module-class](#collector-module-class)) stay enforced.

The collector registry uses the `validate_key` / `validate_scope` callbacks introduced by `req-grid-registry-scope-validators` (see `tap_grid/specs/spec-grid-registry.md`). That registry requirement is an implementation dependency for the collector registry. Both halves of the `scope:key` pair must match the format:

```text
^[A-Za-z0-9][A-Za-z0-9_.\-]*$
```

Validation runs on both `register()` and `get()`, so malformed runner registrations fail loud at startup and malformed persisted `Collector.collector_registry` values fail loud at execution-time lookup. The same validation helper is reused by `Collector.validate()` so the model and the registry cannot drift.

**Future seam — resilient runner resolution (process/registration drift).** `req-tap-cares-collector-registry-3` (Startup Registration) assumes the process that *executes* a collector ran the same trusted-startup `AppConfig.ready()` registration that the enqueuing process did. The Steady Queue topology breaks that assumption: the supervisor is long-lived and forks workers from its boot-time image without hot-reload (`req-tap-cares-task-backend-deployment-3`), so a collector registered after the supervisor booted resolves fine from a fresh `manage.py`/web process but is absent from every worker — surfacing as a confusing, *late*, mid-job `RUNNER_UNAVAILABLE` rather than an early, honest refusal. The hardening must stay inside `req-tap-cares-collector-registry-6` (No Dynamic Code Loading): resolution is **never** "import the runner from the node's persisted dotted path" — that is forbidden and the seam does not relax it. The in-bounds option space: (a) **enqueue-time preflight** — `run_collection` resolves `get_collector` in the (fresh-code) enqueuing process and refuses to create the `CollectionJob` if the runner is unregistered, converting a late confusing worker failure into an immediate, correct, actionable caller error; (b) a **loud self-diagnosing failure message** at the resolution point naming the stale-supervisor cause and the `scripts/dc restart web` fix — *shipped 2026-05-19* in `tap_cares/services.py` as the minimum interim; (c) an optional **registration-generation stamp** so a stale worker can detect "my registration generation < the node's" and fail fast with that diagnosis. This seam pairs with the **collector hot-reload** seam (`req-tap-cares-task-backend-backlog-3`, `spec-tap-cares-task-backend.md`): hot-reload makes a new registration *current* in the executing process; resilient resolution makes its *absence* fail honestly and early until it is. Beyond the shipped interim (b), build on a demand signal.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-registry-1 | Scoped Registry | Implemented | Collector runners are registered in a dedicated `collector_registry` backed by TAP's `ScopedRegistry` pattern. | |
| req-tap-cares-collector-registry-2 | Separate From Search | Implemented | Collector runners do not share `search_runner_registry`. | |
| req-tap-cares-collector-registry-3 | Startup Registration | Implemented | Apps and plugins register collector runners at startup before collector execution. | |
| req-tap-cares-collector-registry-4 | Fully Qualified Lookup | Implemented | Runtime lookup uses the persisted fully qualified `scope:key` value from the Collector node. | |
| req-tap-cares-collector-registry-5 | Duplicate Guard | Implemented | Duplicate registration of the same `(scope, key)` pair is a configuration error. | |
| req-tap-cares-collector-registry-6 | No Dynamic Code Loading | Implemented | Collector execution never imports modules, reads filesystem paths, or evaluates code based on Collector node data. | |
| req-tap-cares-collector-registry-7 | Provenance By Scope | Implemented | Fully qualified keys preserve the runner's registration provenance through the scope portion of `scope:key`. | |
| req-tap-cares-collector-registry-8 | Public Helpers | Implemented | `tap_cares/registry.py` exposes `register_collector(key, cls, *, name, description, scope=None)`, `reconcile_collector_nodes()`, and `get_collector(collector_key)` as the public registration, materialization, and lookup surface, mirroring `tap_grid.registry.register_search_runner` / `get_search_runner`. | |
| req-tap-cares-collector-registry-9 | Resilient Runner Resolution Seam Named | Backlog | The process/registration-drift hardening seam is named here, constrained to stay inside `req-tap-cares-collector-registry-6` (no grid-data code loading). Shipped interim: the loud self-diagnosing `RUNNER_UNAVAILABLE` message (`tap_cares/services.py`). Deferred (demand-signal-gated): enqueue-time preflight in `run_collection`, optional registration-generation stamp. Pairs with `req-tap-cares-task-backend-backlog-3`. | Discovered 2026-05-19: a 28h-stale Steady Queue supervisor surfaced a correctly-registered collector as a confusing mid-job failure on a collector that ran fine from a fresh `manage.py` process. |
| req-tap-cares-collector-registry-9 | Format Validators | Implemented | `collector_registry` is constructed with `validate_key` and `validate_scope` callbacks (per `req-grid-registry-scope-validators`) that enforce `^[A-Za-z0-9][A-Za-z0-9_.\-]*$` on each half of `scope:key`. | |
| req-tap-cares-collector-registry-10 | Shared Validator Helper | Implemented | The same validator function used by the registry is reused by `Collector.validate()` so format rules cannot drift between model-side and registry-side enforcement. | Validator helper now defined; Collector.validate() call site lands with the model in Phase 3. |

## Collector Registration
----
RID: `req-tap-cares-collector-registration`
Status: `Proposed`

Collector dual-existence registration is **split across two phases** so that app `ready()` stays read-only with respect to graph state (`req-tap-plugin-load-v0-ready-readonly`):

- **`register_collector(...)`** runs at app `ready()` and performs **no graph write**. It registers the runner class in `collector_registry` and records the on-grid node descriptor (`name` / `description`) in memory, keyed by `scope:key`, for later materialization.
- **`reconcile_collector_nodes()`** is the deferred grid-side half — the **sole legal path that creates or updates an on-grid `Collector` node**. It runs under whatever actor its caller has bound (the boot orchestrator today) and materializes every registered collector's node in one `write_batch`.

A `Collector` row is therefore never written at `ready()`, and never by generic `create_node`, GRIFT seeds, or direct ORM — all closed by `Collector.INTERNAL_ONLY = True`. The only writer is `reconcile_collector_nodes()`, via the trusted-internal batch path.

Splitting the two halves is what lets `ready()` avoid writing the grid before a named actor exists: a fresh standup that wrote at `ready()` would either fail closed (no actor) or be silently masked, leaving an empty Collector inventory.

#### Signatures

```python
def register_collector(
    key: str,
    cls: type[CollectorBase],
    *,
    scope: str,
    name: str,
    description: str,
) -> None:
    """Register a collector capability — the read-only half of dual existence.

    Runs at app `ready()` and performs NO graph write:
    1. Registers `cls` in `collector_registry` under `scope:key`. `scope` is
       REQUIRED and must be the plugin's stable slug — it is deliberately NOT
       inferred from `cls.__module__`, because the collector's derived entity id
       is a durable, cross-referenced grid key that a module rename must never
       silently change (req-tap-cares-collector-model-10).
    2. Records the on-grid node descriptor (`name` / `description`) in
       `_COLLECTOR_NODE_METADATA`, keyed by `scope:key`, for later
       materialization by `reconcile_collector_nodes()`.
    """


def reconcile_collector_nodes() -> dict[str, int]:
    """Materialize the on-grid Collector node for every registered collector.

    The deferred grid-side half. Under the caller-bound actor, in one
    `write_batch`: creates missing nodes, patches drifted name/description,
    no-ops the rest. Returns {created, updated, unchanged} counts. For each:
      - entity_id = uuid5(NAMESPACE_COLLECTOR, f"{scope}:{key}")
      - collector_registry = f"{scope}:{key}"

    A collector registered with no recorded descriptor is an internal-
    consistency violation and raises ImproperlyConfigured (never a silent
    skip) — boot relies on this reconcile to create Collector nodes.
    """
```

`name` and `description` are required keyword arguments. Plugin authors must provide human-readable identity for the on-grid node; collectors that ship to a TAP installation become visible in Administrivia surfaces and must carry display metadata appropriate for that visibility. There is no v0 default value or implicit fallback.

#### Plugin-side usage

```python
# plugins/<slug>/apps.py
class <Plugin>Config(TapPluginConfig):
    def ready(self) -> None:
        from tap_cares.registry import register_collector
        from plugins.<slug>.collectors.<module> import <Class>

        register_collector(
            key="<short-key>",
            cls=<Class>,
            name="Human-Readable Name",
            description="One-line description of what this collector does.",
        )
```

`register_collector` at `ready()` only records the runner and its descriptor — it writes nothing to the grid. The on-grid `Collector` node is created (and thereafter converged) by `reconcile_collector_nodes()`, which the boot orchestrator runs under a bound actor after `ready()`. Identity stays stable across reconciles because `entity_id` is deterministic; `name` and `description` converge to whatever the plugin currently declares.

#### Identity derivation

Per `req-grid-dual-existence-identity`, the on-grid `entity_id` is:

```python
entity_id = uuid.uuid5(NAMESPACE_COLLECTOR, f"{scope}:{key}")
```

`NAMESPACE_COLLECTOR` is a module-level UUID constant in `tap_cares/registry.py`. Once set, it is immutable — changing it would re-identify every Collector node on every grid.

#### Materialization

`reconcile_collector_nodes()` is the public materialization surface — it lives alongside `register_collector` in `tap_cares/registry.py` and is the function the boot orchestrator calls under a bound actor. It writes through `write_batch(..., _internal_only_bypass=True)` (the trusted-internal escape hatch that `Collector.INTERNAL_ONLY` otherwise closes), so the full write pipeline runs for every collector node in one batch.

When the dual-existence pattern lands a second concrete consumer (Emitter, Action, or Receiver), this materialization step is a candidate for consolidation into a shared registration mechanism per `req-grid-dual-existence-consolidation` in `spec-grid-dual-existence.md`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-registration-1 | Split Registration Surface | Proposed | `register_collector(key, cls, *, name, description, scope=None)` registers the runner read-only at `ready()`; `reconcile_collector_nodes()` is the sole legal path that creates an on-grid `Collector` row. | |
| req-tap-cares-collector-registration-2 | Read-Only Registration | Proposed | `register_collector` performs no graph write: it registers the runner class in `collector_registry` and records the on-grid node descriptor in memory for later materialization (`req-tap-plugin-load-v0-ready-readonly`). | |
| req-tap-cares-collector-registration-3 | Required Display Metadata | Proposed | `name` and `description` are required keyword arguments. No default values or implicit fallbacks. | |
| req-tap-cares-collector-registration-4 | Deterministic Identity | Proposed | The on-grid `entity_id` is `uuid5(NAMESPACE_COLLECTOR, f"{scope}:{key}")`. | |
| req-tap-cares-collector-registration-5 | Idempotent Reconcile | Proposed | Repeated `reconcile_collector_nodes()` calls converge: create missing nodes, patch drifted `name`/`description`, no-op the rest; identity stays stable. | |
| req-tap-cares-collector-registration-6 | Trusted-Internal Batch Write | Proposed | `reconcile_collector_nodes()` materializes nodes via `write_batch(..., _internal_only_bypass=True)` from `tap_grid.services` so the full write pipeline runs. | See `req-grid-service-write-internal-create`. |
| req-tap-cares-collector-registration-7 | Materialization Colocation | Proposed | `reconcile_collector_nodes()` lives in `tap_cares/registry.py` alongside `register_collector` as the public materialization surface. | Migration candidate for the shared mechanism in `req-grid-dual-existence-consolidation`. |
| req-tap-cares-collector-registration-8 | Namespace UUID Stable | Proposed | `NAMESPACE_COLLECTOR` in `tap_cares/registry.py` is a module-level constant; changing it is a grid-wide identity break and not permitted. | |
| req-tap-cares-collector-registration-9 | Missing Descriptor Fails Loud | Proposed | `reconcile_collector_nodes()` raises `ImproperlyConfigured` if a registered collector has no recorded descriptor; it never partially reconciles by skipping the node. | Boot depends on this reconcile to create Collector nodes. |

## Collector Concurrency Policy
----
RID: `req-tap-cares-collector-concurrency`
Status: `Backlog`

Each `Collector` should eventually declare how many simultaneous runs of that collector may be active.

Possible future model field:

```python
max_concurrent_runs = models.PositiveIntegerField(default=1)
```

This requirement is intentionally Backlog until the collector enqueue path, scheduler behavior, and future API trigger surface are untangled together. Concurrency touches all three: manual runs, scheduled runs, and any future externally-triggered collection request need one authoritative policy.

The likely shape is a field stored on the on-grid `Collector` node. Concurrency would be evaluated per `Collector` entity: before enqueuing a new collection job, tap-cares would count active `CollectionJob` records linked from that collector through `HAS_COLLECTION_JOB` whose status is `RUNNING`. If the active count is greater than or equal to `Collector.max_concurrent_runs`, the service layer would refuse to enqueue another job.

The expected default is `1` because most collectors are safer as singleton execution paths until a concrete need for parallel collection exists. The FedRAMP 20x KSI catalog collector should remain singleton; there is no useful reason to refresh the same catalog source multiple times at once.

`max_concurrent_runs` must be a positive integer. `0` is not a disablement mechanism; capability enable/disable is separately tracked as backlog work in `spec-tap-cares-v0.md`.

When implemented, the service layer must be authoritative. Administrative pages may disable or guard Run buttons based on this field, but UI behavior is advisory. Manual runs, future scheduler-triggered runs, and any API-triggered runs must all route through the same concurrency guard.

This requirement intentionally scopes v0 concurrency to one `Collector` node. Today `collector_registry` is unique, so a collector node and a registered runner are effectively one-to-one. If future per-instance configuration allows multiple Collector nodes to share one runner, a later requirement should decide whether concurrency remains per node or moves to a shared `concurrency_key` / runner-level policy.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-concurrency-1 | Field Declared | Backlog | `Collector` declares a positive integer `max_concurrent_runs` field with default `1`. | |
| req-tap-cares-collector-concurrency-2 | Positive Value Required | Backlog | `max_concurrent_runs` must be greater than or equal to `1`; `0` is invalid. | Disablement remains a separate backlog concern. |
| req-tap-cares-collector-concurrency-3 | Service-Layer Guard | Backlog | `run_collection()` refuses to create/enqueue a new job when linked `RUNNING` jobs meet or exceed the collector limit. | |
| req-tap-cares-collector-concurrency-4 | UI Reflects Policy | Backlog | Administrivia surfaces disable, guard, or explain manual Run actions when the concurrency limit is already reached. | Service layer remains authoritative. |
| req-tap-cares-collector-concurrency-5 | KSI Singleton | Backlog | The FedRAMP 20x KSI collector is configured for one simultaneous run. | |
| req-tap-cares-collector-concurrency-6 | Future Shared Runner Scope Deferred | Backlog | Any runner-level or shared-key concurrency across multiple Collector nodes is deferred until per-instance collector configuration exists. | |

## Collector Module Class
----
RID: `req-tap-cares-collector-module-class`
Status: `Implemented`

The `collector_registry` registers collector classes that inherit from `CollectorBase`.

A collector class is the Python implementation of a collector capability. tap-cares resolves the `Collector.collector_registry` key, retrieves the registered class, builds a `CollectorConfig`, instantiates the class with that config, and invokes its `run()` method.

`CollectorBase` is an abstract base class defined in `tap_cares` that fixes the constructor signature and declares `run()` as an abstract method:

```python
from abc import ABC, abstractmethod

class CollectorBase(ABC):
    def __init__(self, config: CollectorConfig) -> None:
        self.config = config

    @abstractmethod
    def run(self) -> None: ...
```

v0 collector class shape:

```python
class ExampleCollector(CollectorBase):
    def run(self) -> None:
        ...
```

`register_collector` checks `issubclass(cls, CollectorBase)` and rejects anything else — factory functions, lambdas, plain classes that happen to define `run()`, or already-instantiated objects all fail at registration time.

The class constructor receives the `CollectorConfig`. The `run()` method receives no direct arguments in v0. Per-run information should be carried in `CollectorConfig` so the collector instance is self-contained for the duration of a run.

The module class contract intentionally avoids factory functions in v0. Registered classes are simpler to inspect, simpler to document, and easier for future skills to scaffold consistently. Reusable behavior belongs in tap-cares collector runtime helpers and shared base classes, not in plugin-specific factory setup.

Collector classes should be written as thread/process-compatible units of work:

- no reliance on request-local state
- no reliance on shared mutable module globals
- no assumption that execution occurs in the web process
- no arbitrary grid mutation below the approved GRIFT import surface
- no dependency on receiving live Django model instances in the public collector API

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-module-class-1 | Registry Stores Classes | Implemented | `collector_registry` entries resolve to collector classes rather than filesystem paths, import strings, or factory functions. | |
| req-tap-cares-collector-module-class-2 | Constructor Receives Config | Implemented | tap-cares instantiates collector classes with a `CollectorConfig` object. | |
| req-tap-cares-collector-module-class-3 | Run Method | Implemented | Collector classes expose `run(self)` as the v0 execution method. | |
| req-tap-cares-collector-module-class-4 | No Run Arguments | Implemented | v0 `run()` receives no direct arguments; per-run data flows through `CollectorConfig`. | |
| req-tap-cares-collector-module-class-5 | Process-Compatible Shape | Implemented | Collector classes are specified so they can later execute outside the web process without changing the public class contract. | |
| req-tap-cares-collector-module-class-6 | CollectorBase Subclass | Implemented | Registered collector classes must inherit from `tap_cares`'s `CollectorBase` abstract base. `register_collector` rejects non-subclasses at registration time. | |
| req-tap-cares-collector-module-class-7 | Abstract Run | Implemented | `CollectorBase.run` is declared `@abstractmethod`, so concrete subclasses must override it before instantiation succeeds. | |

## Collector Packaging
----
RID: `req-tap-cares-collector-packaging`
Status: `Refactoring`

A collector is a self-contained subpackage so a plugin with more than one collector stays unambiguous.

Layout:

- Each collector lives in `<plugin>/collectors/<name>_collector/` — a Python package (`__init__.py`) that owns the collector's `CollectorBase` subclass and **all** of its assets (manifest + schema, pinned reference data, safety denylists, fixtures, …). Assets are namespaced inside the collector package, never as siblings directly under `<plugin>/collectors/`.
- `<plugin>/collectors/__init__.py` is a namespace marker only; it holds no collector implementation or shared collector assets.
- Collectors register with tap-cares in `<plugin>/apps.py` via `register_collector` ([req-tap-cares-collector-registration](#collector-registration)).

Rationale: the moment a plugin has two collectors, flat modules plus shared sibling asset directories under `collectors/` become ambiguous ("whose `pinned/`?"). A self-contained per-collector package keeps ownership of code and assets unambiguous, mirrors how plugins themselves are self-contained, and gives a future build-collector skill one fixed shape to scaffold.

Current conformance (honest record per the no-messy-specs discipline): the boto3 `aws_core` collector (`plugins/aws_core/collectors/boto3_collector/`) conforms. The `fedramp_20x_ksi` KSI collector predates this clarification — it is a flat `collectors/ksi_catalog.py` module with sibling `collectors/pinned/` and `collectors/safety/` asset directories. KSI is the working reference collector; bringing it into conformance (move into a `collectors/ksi_*_collector/` package; update the `apps.py` import path, the in-module `pinned/`/`safety/` path resolution, and tests) is a tracked, gated follow-up, deliberately deferred until the boto3 make-it-work pass is complete so the reference collector is not destabilized mid-build.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-packaging-1 | Self-Contained Package | Refactoring | Each collector is a `<plugin>/collectors/<name>_collector/` package owning its `CollectorBase` subclass and all its assets. | boto3 conforms. |
| req-tap-cares-collector-packaging-2 | Namespace-Only Collectors Init | Refactoring | `<plugin>/collectors/__init__.py` is a namespace marker; no collector implementation or shared collector assets live directly under `collectors/`. | |
| req-tap-cares-collector-packaging-3 | Registration In apps.py | Implemented | Collectors register via `register_collector` in `<plugin>/apps.py`. | Already true for KSI and the boto3 collector. |
| req-tap-cares-collector-packaging-4 | KSI Conformance Pending | Refactoring | The KSI reference collector predates this convention; conformance is a tracked, gated follow-up (post-boto3-make-it-work). | Honest record of current non-conformance. |

## CollectorConfig
----
RID: `req-tap-cares-collector-config`
Status: `Implemented`

`CollectorConfig` is the configuration object tap-cares passes to a collector class at construction time.

`CollectorConfig` is built by tap-cares, not by plugin code. In v0, it is derived only from the `Collector` node and the collection job being executed. Future versions may add JSON-safe execution data supplied by a scheduler or manual run surface.

The detailed contents of `CollectorConfig` will be refined as the first concrete collector is implemented. v0 should keep the shape deliberately small for the FedRAMP 20x KSI collector, where most behavior can be hard-coded in the registered collector class.

v0 shape — a frozen dataclass carrying exactly two identifiers:

```python
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True, slots=True)
class CollectorConfig:
    collector_entity_id: UUID
    collection_job_entity_id: UUID
```

These two IDs match the JSON-safe task arguments listed in [Collector Task Execution](#collector-task-execution); the task worker reconstructs the `CollectorConfig` from them after dequeuing. No `params` dict, no scheduler-supplied overrides, no per-instance Collector configuration in v0. Additional fields are introduced when the second concrete collector arrives and demonstrates a real shape requirement.

Design constraints (forward-looking):

- `CollectorConfig` must be JSON-serializable or reducible to a JSON-serializable payload.
- `CollectorConfig` should carry identifiers and configuration data, not live Django model instances.
- `CollectorConfig` should be suitable for transmission to a worker process.
- future collector-specific configuration should be modeled as JSON data, not Python objects.

This shape keeps collector modules compatible with future stricter process isolation.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-config-1 | Built By tap-cares | Implemented | tap-cares builds `CollectorConfig` before instantiating a collector class. | Construction site lands with the task runtime in Phase 5; the type is callable from anywhere now. |
| req-tap-cares-collector-config-2 | Constructor Input | Implemented | `CollectorConfig` is passed to the collector class constructor. | |
| req-tap-cares-collector-config-3 | JSON-Safe Shape | Implemented | `CollectorConfig` is JSON-serializable or reducible to JSON-safe data. | |
| req-tap-cares-collector-config-4 | No Live Model Requirement | Implemented | The public collector module contract does not require live Django model instances inside `CollectorConfig`. | |
| req-tap-cares-collector-config-5 | Future Isolation Ready | Implemented | The config shape can be passed across a process boundary without changing the collector class contract. | |
| req-tap-cares-collector-config-6 | v0 Shape Is Two IDs | Implemented | The v0 `CollectorConfig` is a frozen dataclass containing exactly `collector_entity_id: UUID` and `collection_job_entity_id: UUID`. No params dict, no scheduler overrides. | |

## Collector Self-Test And Readiness
----
RID: `req-tap-cares-collector-self-test`
Status: `Approved for Development`

Every collector runner exposes a self-test that answers an operator-facing question before execution:

> "Does this collector currently appear ready to run, and if not, what should I fix?"

The self-test is **synchronous** and **runtime-evaluated**: readiness is computed on demand from registered runner code, locally discovered configuration/secrets, local runtime dependencies, and read-only external checks the collector owns. It does **not** run as a Django Task — it is timeout-bounded (see [Bounded Latency](#bounded-latency)) and fits inside a synchronous request and inside the run-task precondition gate. There is no async self-test path and no task-result polling. (The task backend has no return-value fetch; an async self-test would need a polled result store and buys nothing over a bounded synchronous call.)

Self-test is **phase 1 of a collection run**, not a separate subsystem. Every run is two phases: **phase 1 — self-test**, **phase 2 — execute**. A `CollectionJob` carries a **run mode**: a *full run* does phase 1 then, if runnable, phase 2; a *self-test-only run* does phase 1 and stops. A one-off readiness check (the Administrivia Self-test button, an agent probe) is simply a self-test-only `CollectionJob` — same vehicle, same async path, same failure surfacing, no separate readiness subsystem.

The structured self-test result IS persisted, on the `CollectionJob` itself in a dedicated `self_test` field (see [Self-Test As Run Phase 1](#self-test-as-run-phase-1)) — not in a separate readiness entity, and never as a mutable field on the immutable `Collector` node. "It worked for me at *&lt;time&gt;*" is answered from `CollectionJob` history: the latest job's `self_test` is current best-known readiness; the first job whose phase 1 failed is when it broke. One unified run+readiness history, not two parallel stores.

Persistence and logs are complementary, not redundant. The **log line** is the per-invocation narrative (ordered, cross-component, ephemeral; site-ID convention). The **`CollectionJob`** is the queryable point-in-time state (`self_test` result + `checked_at` + run outcome). The log answers *what happened*; the job record answers *what was true, when, and is it still*. Neither is reconstructed from the other; both are redaction-safe.

The self-test serves both humans and future agents: Administrivia renders status and gates run buttons; the run task uses it as a default precondition (see [Run Gating](#run-gating)); checks may carry references to canonical plugin documentation (doc-ref *resolution* is deferred — `req-tap-cares-collector-self-test-5`).

### Status Vocabulary

Self-test status is deliberately separate from `CollectionJob.status`. A `CollectionJob` says what happened to one run. Collector readiness says whether a run should be attempted now.

Allowed readiness statuses:

| Status | Meaning |
| --- | --- |
| `ready` | All required self-test checks passed. The collector can be run. |
| `warning` | Required checks passed, but one or more non-blocking checks found a degraded or advisory condition. The collector can be run. |
| `unconfigured` | Required user/operator configuration is absent. Example: a collector target/config object has not been provided. The collector must not be run from the UI. |
| `misconfigured` | Configuration exists but is invalid, incomplete, internally inconsistent, or references missing local material such as an unloaded secret file. The collector must not be run from the UI. |
| `error` | The self-test could not complete because runner code is unavailable, a diagnostic crashed, or a required runtime/external dependency failed in a way that is not simply missing or malformed configuration. The collector must not be run from the UI. |

There are intentionally no separate `blocked` or `unavailable` readiness statuses in v0. Those cases collapse into `error` with specific check codes and messages:

- Missing runner code: `error` with a `RUNNER_UNAVAILABLE` check.
- Missing binary or local runtime dependency: `error` with a dependency-specific check.
- External endpoint unreachable during a read-only connectivity test: `error` with an upstream-specific check.

`blocked` is **not** a status — neither a readiness status nor a `CollectionJob` status. A failed phase-1 self-test is surfaced through the **standard collector failure mode** (`req-tap-cares-collector-failure-mode`): the `CollectionJob` terminates `FAILED`, the self-test summary becomes the failure reason, and the structured result lands in `CollectionJob.self_test`. A passing self-test-only run terminates `SUCCESSFUL` ("self-test passed; no collection performed"). No new lifecycle status is introduced.

### Result Shape

tap-cares provides small frozen value objects for self-test results. The field set below is the contract; the live implementation is `tap_cares/collectors/readiness.py`.

```python
class CollectorReadinessStatus(StrEnum):
    READY = "ready"
    WARNING = "warning"
    UNCONFIGURED = "unconfigured"
    MISCONFIGURED = "misconfigured"
    ERROR = "error"

class CollectorSelfTestCheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

@dataclass(frozen=True, slots=True)
class CollectorDocRef:
    plugin: str
    doc: str
    section: str = ""
    label: str = ""

@dataclass(frozen=True, slots=True)
class CollectorSelfTestCheck:
    code: str
    status: CollectorSelfTestCheckStatus
    message: str
    readiness_status: CollectorReadinessStatus | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    docs: tuple[CollectorDocRef, ...] = ()

@dataclass(frozen=True, slots=True)
class CollectorSelfTestResult:
    status: CollectorReadinessStatus
    summary: str
    checked_at: datetime
    checks: tuple[CollectorSelfTestCheck, ...] = ()
    collector_registry: str = ""
    docs: tuple[CollectorDocRef, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)
```

Contract semantics:

- `status` is the headline readiness value for tables, badges, the stored `CollectionJob.self_test`, API responses, and the phase-1 gate.
- `summary` is a short operator-facing explanation.
- `checked_at` is the UTC instant the result was produced. It is **mandatory**: the stored `CollectionJob.self_test` and the "it worked at *&lt;time&gt;*" answer depend on it. (The earlier draft made this optional and mis-ordered it after defaulted fields — an invalid dataclass; it is now required and ordered before defaulted fields.)
- `checks` is the accumulated list of every diagnostic the collector could evaluate in one pass.
- `collector_registry` is stamped by the service entry point so a detached result is self-describing.
- `docs` on the result points to broad setup/operation docs; `docs` on a check points to the most specific section. This subsystem is only the *emitter* (`req-tap-cares-collector-self-test-5`); refs are emitted now. *Resolution* (ref → canonical doc target) is the docs-system concern `specs/spec-docs.md` `req-docs-ref-resolution`; *rendering* (resolved target → navigable link) is the web concern `tap_web/specs/spec-web-rendering.md` `req-web-rendering-docref`. Both deferred (Backlog).
- `context` is JSON-safe and **redaction-safe**: secret material must never appear, in the result or any check, in memory, the log line, or the stored `CollectionJob.self_test`.
- The `CollectorDocRef` field names (`plugin`, `doc`, `section`, `label`) are the contract, reconciled with the implementation so the spec stays canonical.

### Accumulation

Self-tests must accumulate diagnostics instead of bailing at the first failure whenever it is practical and safe to continue.

Example AWS first-run shape (a zero-config, secret-discovered AWS collector
— illustrative and collector-agnostic):

| Check | Status | Notes |
| --- | --- | --- |
| `AWS_SECRET_PRESENT` | `fail` | No `aws_static_access_key` secret found at the well-known `SecretRef`. Readiness `unconfigured`. |
| `SECRET_VALID` | `skip` | No secret loaded, so its credential schema cannot be validated. |
| `TOOL_AVAILABLE` | `pass` or `fail` | A local dependency/tool check runs independently of the secret. |
| `AWS_IDENTITY` | `skip` | No credentials, so read-only STS identity cannot run. |

The goal is the fullest useful "here is everything known right now" picture so users are not walked through one error at a time.

**Skip semantics (pinned).** A `skip` records that a check could not run because an input it depends on was absent. It is *informational, not a failure, and does not by itself escalate readiness*. Top-level status derives only from checks that actually failed (`fail`) or raised a genuine advisory (`warn`):

- any `fail` → the most specific non-runnable status among the failures (`unconfigured` / `misconfigured` / `error`, as each failing check assigns).
- no `fail`, ≥1 `warn` → `warning`.
- no `fail`, no `warn` (only `pass`/`skip`) → `ready`.

A skip-only result is `ready`: the collector is ready for everything it could test, and what it could not test was gated by an input that is not itself a failure. This pins a previously unspecified case; the implementation's `check_skip` / `_derive_status` must align (a `skip` must not set `readiness_status=WARNING` or force top-level `warning`).

### Live Check Boundary

Self-tests may be semi-live. A collector should test as far toward real execution as it can go without mutating the grid or causing external side effects.

Allowed:

- read-only HTTP reachability checks
- read-only credential validation
- local binary/dependency checks
- read-only cloud identity calls such as AWS STS `GetCallerIdentity`
- lightweight source endpoint reachability checks

Not allowed:

- grid mutation
- GRIFT import
- writing to external systems
- creating schedules, jobs, or action records
- broad inventory collection disguised as readiness

Concrete scoping examples:

- The FedRAMP KSI self-test only confirms the collector can reach its pinned upstream URL (read-only HEAD, GET fallback). It must not validate the full upstream catalog, compute a diff, or test FedRAMP content health; those belong to a collection run.
- A zero-config, secret-discovered AWS collector's self-test resolves the single well-known `SecretRef` (no operator config object), validates the AWS credential schema, checks its local tool/dependency availability, and performs a read-only STS `GetCallerIdentity` matched against the secret's `metadata.account_id`. It stops short of inventory collection and GRIFT authoring.

### Bounded Latency

Self-test runs on a synchronous request path and inside the run-task gate, so it MUST be bounded:

- Every live check (HTTP reachability, STS identity, subprocess probe) carries an explicit timeout. The v0 *default* budget is ≤ 5s per live check. A collector that depends on an external tool with unavoidable cold-start (e.g. one that shells out to an external CLI or service whose process or embedded service cold-starts on each invocation) MAY declare a larger **per-collector** budget via the `CollectorBase.SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS` / `SELF_TEST_AGGREGATE_DEADLINE_SECONDS` class attributes, but MUST document the justification at the override site. Controlled slowness is acceptable; an unbounded or hand-tuned-magic timeout is not.
- The aggregate self-test target is a few seconds; the default hard ceiling is ~15s total, scaled by the same per-collector override when a larger live-check budget is declared. A check that would exceed its (default or declared) timeout records an explicit non-pass result — `fail`/`error`, or `skip` when "could not determine in time" is more honest than "broken" — rather than hanging the request or a worker thread.
- A timed-out dependency check is never a silent pass: it is an explicit non-pass check with its own code, so the operator sees "could not verify in time", not a false green.

### Runner Contract

`CollectorBase` exposes a synchronous self-test hook with a default implementation:

```python
class CollectorBase(ABC):
    @classmethod
    def self_test(cls) -> CollectorSelfTestResult:
        ...
```

The default implementation returns `ready` with a single `RUNNER_REGISTERED` pass-level check ("a runner exists; no collector-specific self-test is defined"). This is **safe by construction** under the default-on run gate (see [Run Gating](#run-gating)): a collector that declares no meaningful self-test also has nothing to gate on, so default `ready` → run proceeds → behavior is unchanged for trivial collectors. Overriding `self_test()` is exactly how a collector opts into real readiness gating. The earlier `SELF_TEST_NOT_IMPLEMENTED`-warning alternative is rejected: with the gate default-on, a base `warning` would needlessly degrade every collector that has no readiness concept.

**v0 single ambient target.** `self_test()` takes no arguments and is a `classmethod`. It evaluates against a single ambient target the collector discovers itself — for AWS, the single well-known `SecretRef`; for KSI, the pinned URL constant. There is intentionally no per-`Collector`-node configuration in v0, so two `Collector` rows backed by the same runner class self-test identically. Per-target configuration (`self_test(config=...)` or a configured target model) is deferred; the contract leaves space for it without forcing the durable model before a second concrete configured collector proves the shape.

`self_test()` itself is **pure**: it computes and returns a `CollectorSelfTestResult` and performs no grid mutation, GRIFT, job/schedule creation, or external writes (`req-tap-cares-collector-self-test-6`). Registry resolution, exception trapping, logging, and persistence are the *service entry point's* responsibility, not the check code's.

### Service Entry Point

`tap_cares.services.self_test_collector(collector: Collector) -> CollectorSelfTestResult` is the single entry point every caller uses (Administrivia button/detail, the run-task gate). It owns the cross-cutting concerns the pure hook deliberately excludes:

1. **Registry resolution.** Resolve the runner via `get_collector(collector.collector_registry)`. If unregistered, synthesize `error` with a `RUNNER_UNAVAILABLE` check — this is the canonical producer of the `RUNNER_UNAVAILABLE` code named in the status vocabulary.
2. **Exception trapping.** If the runner's `self_test()` raises, trap it into `error` with a `SELF_TEST_EXCEPTION` check (exception type only — no secret-bearing detail) and log at `exception` level. A crashing diagnostic is itself a non-runnable readiness signal, never a 500.
3. **Stamping.** Stamp `collector_registry` and `checked_at` so the returned result is self-describing.
4. **Log.** Emit the site-ID backend summary (see [Logging](#logging)).
5. **Return, do not persist.** The entry point returns the result synchronously; it does not write the grid. The run-task body records the result onto `CollectionJob.self_test` and, on a non-runnable result, fails the job via the standard failure mode (see [Self-Test As Run Phase 1](#self-test-as-run-phase-1)). This preserves the sole-writer invariant: only the run-task body writes the `CollectionJob`.

The result is returned to the caller synchronously regardless of which branch produced it. The Administrivia Self-test button calls this same entry point as phase 1 of a `self_test_only` `CollectionJob`.

### Self-Test As Run Phase 1

Self-test is the first phase of a `CollectionJob`, not a separate persisted entity.

- **Run mode.** `CollectionJob` carries a run-mode discriminator: `full` (phase 1 → if runnable, phase 2 collect) or `self_test_only` (phase 1 → stop). Manual Run and scheduler create `full` jobs; the Administrivia Self-test button and agent/one-off readiness probes create `self_test_only` jobs. Both are ordinary `CollectionJob`s on the standard async path.
- **Phase 1.** The run-task body calls `self_test_collector(collector)` (see [Service Entry Point](#service-entry-point)) before any external collection work or GRIFT.
- **Storage.** The full structured `CollectorSelfTestResult` is written to a dedicated `CollectionJob.self_test` field by the run-task body — consistent with the `CollectionJob` sole-writer invariant (`req-tap-cares-collector-job-sole-writer`). It is kept distinct from the `results` phase-2 accumulator and the `PRODUCED_BATCH` edges so readiness stays queryable on its own: "latest readiness for collector X" = the most recent `CollectionJob.self_test`; readiness-over-time = that field across the collector's `CollectionJob` history.
- **Non-runnable ⇒ standard failure mode.** If phase-1 readiness is not runnable (`unconfigured` / `misconfigured` / `error`), the collector bails before phase 2 via the standard collector failure mode (`req-tap-cares-collector-failure-mode`): `CollectionJob` ends `FAILED`, `summary` from the self-test summary, full detail in `self_test`, no phase-2 work, no GRIFT, no partial writes. Not hidden — an ordinary, visible way a collector fails within its thread.
- **Runnable.** A `full` job proceeds to phase 2. A `self_test_only` job terminates `SUCCESSFUL` with summary "self-test passed; no collection performed" and `self_test` populated.
- **Redaction-safe.** `self_test` is a place secret-ish material could leak (e.g. an AWS error string carrying an ARN); it carries the same redaction contract as logs and `context`.

There is no separate readiness entity, no transition-append store, and no `blocked` status in v0. The `CollectionJob` history is the unified run+readiness record.

### Logging

Every self-test invocation (via the service entry point) emits one backend log summary — INFO when runnable, WARNING when not — using the repository's stable site-ID convention, including:

- collector registry key
- top-level readiness status
- count of pass/warn/fail/skip checks
- summary

Per-check detail may be logged at DEBUG. The log is the per-invocation **narrative**; `CollectionJob.self_test` is the queryable **state**. Neither is reconstructed from the other; both are redaction-safe.

### Run Gating

Two gates, different authority:

1. **UI courtesy gate.** Administrivia disables the manual Run button (and renders status) from the latest `CollectionJob.self_test` for that collector — a cheap field read, no live check on the table poll. It stops an operator clicking a doomed run; convenience, not enforcement.
2. **Authoritative phase-1 gate (default-on).** Every `CollectionJob` runs phase-1 self-test in the run-task body before any external work or GRIFT (see [Self-Test As Run Phase 1](#self-test-as-run-phase-1)). Non-runnable ⇒ the job ends `FAILED` via the standard failure mode; runnable ⇒ a `full` job proceeds to phase 2, a `self_test_only` job stops `SUCCESSFUL`. This is the authoritative answer to what `req-tap-cares-collector-self-test-10` previously deferred.

The phase-1 gate is **default-on for every collector** and safe by construction: a collector with no meaningful `self_test()` returns the default `ready` and proceeds unchanged. It is uniform across the manual path and the now-implemented scheduler (`tap_cares/specs/spec-tap-cares-scheduler.md`): the scheduler creates a `full` `CollectionJob` like any other caller, and the phase-1 gate protects scheduled runs where no human is watching a Status column. A misconfigured collector on a schedule therefore produces visible `FAILED` jobs with a clear phase-1 reason — deliberately surfaced, not suppressed. It is a fast-fail filter, **not** a correctness guarantee: a self-test passing then phase 2 failing (e.g. a secret rotated in the intervening seconds) is still possible, so collectors must remain robust in phase 2; a green self-test is not "the run cannot fail".

Whether a high-frequency scheduled fire reuses a recent `CollectionJob.self_test` within a freshness window instead of re-running phase 1 is an explicit scheduler-policy decision, deferred to `spec-tap-cares-scheduler.md`. A per-collector opt-out of the default phase-1 gate is likewise deferred; v0 is default-on with no override.

### Future

- **Tiered self-tests.** A self-test currently means "this collector with this configuration". A future split into tiers — checks that run *before* configuration is resolved (binary present, plugin importable) versus *after* (this configuration's secret valid, this account reachable) — lets the UI distinguish "collector is fundamentally broken" from "this target is misconfigured". Backlog.
- **Per-configuration self-test.** When collectors gain multiple configurations / collection targets, the unit of self-test becomes (collector, configuration) and the hook gains a configuration argument (`self_test(config=...)`) or moves onto a configured-target model. v0's single ambient configuration (AWS = the one well-known secret) is the degenerate case. Backlog.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-self-test-1 | Synchronous Self-Test Hook | In Development | `CollectorBase` exposes a synchronous no-arg `self_test()` classmethod returning `CollectorSelfTestResult`; concrete collectors override it. Never a Django Task. | |
| req-tap-cares-collector-self-test-2 | Result Stored On CollectionJob | Proposed | The full structured result is written to a dedicated `CollectionJob.self_test` field by the run-task body (sole-writer), distinct from the `results` accumulator and the `PRODUCED_BATCH` edges. No separate readiness entity; `CollectionJob` history is the unified run+readiness store. **Deliberate reversal** of the original "never persisted" position. | |
| req-tap-cares-collector-self-test-3 | Status Vocabulary | In Development | Readiness is one of `ready` / `warning` / `unconfigured` / `misconfigured` / `error`. `blocked` / `unavailable` are not statuses at all; a failed self-test uses the standard failure mode. | |
| req-tap-cares-collector-self-test-4 | Accumulated Checks | In Development | Self-tests accumulate pass/warn/fail/skip instead of bailing at first failure. | |
| req-tap-cares-collector-self-test-5 | Docs References (resolution deferred) | Proposed | Results/checks may carry `CollectorDocRef`s; this is the *emitter* only — refs are emitted now. | Resolution: `specs/spec-docs.md` `req-docs-ref-resolution`; rendering: `tap_web` `req-web-rendering-docref`; both Backlog. |
| req-tap-cares-collector-self-test-6 | Pure Hook, No Side Effects | In Development | `self_test()` itself performs no grid mutation, GRIFT, job/schedule creation, or external writes. Persistence/logging belong to the service entry point. | Read-only external reads allowed. |
| req-tap-cares-collector-self-test-7 | Semi-Live, Bounded | Proposed | Read-only live checks (upstream reachability, STS identity) are allowed and MUST be timeout-bounded per Bounded Latency. | |
| req-tap-cares-collector-self-test-8 | Backend Log Summary | Proposed | Each invocation emits one redaction-safe site-ID log summary (key, status, check counts, summary). | |
| req-tap-cares-collector-self-test-9 | UI Courtesy Gate | Proposed | Administrivia disables manual Run for `unconfigured` / `misconfigured` / `error`; `ready` / `warning` runnable. | Cross-ref `spec-tap-cares-administrivia.md`. |
| req-tap-cares-collector-self-test-10 | Default-On Phase-1 Gate | Proposed | Every `CollectionJob` runs phase-1 self-test before external work/GRIFT; non-runnable ⇒ job ends `FAILED` via the standard failure mode (no `blocked` status), no partial work. Default-on for all collectors; resolves the previously-deferred service guard. | Per-collector opt-out and scheduler per-fire freshness policy deferred to `spec-tap-cares-scheduler.md`. |
| req-tap-cares-collector-self-test-11 | Service Entry Point | Proposed | `tap_cares.services.self_test_collector(collector)` owns registry resolution (`RUNNER_UNAVAILABLE`), exception trapping (`SELF_TEST_EXCEPTION`), stamping, and logging, then returns the result. It does NOT write the grid; the run-task body persists to `CollectionJob.self_test`. Single caller-facing entry point. | |
| req-tap-cares-collector-self-test-12 | Bounded Latency | Proposed | Per-collector declared budget: default ≤ 5s per live check / ~15s aggregate; a collector with unavoidable external-tool cold-start MAY raise it via `CollectorBase.SELF_TEST_{LIVE_CHECK_TIMEOUT,AGGREGATE_DEADLINE}_SECONDS` with documented justification. Timeouts still record explicit non-pass checks, never hang or false-green. | Per-collector budget added 2026-05-17 to support collectors with unavoidable external-tool cold-start. |
| req-tap-cares-collector-self-test-13 | Redaction-Safe Everywhere | Proposed | No secret material in result, checks, `context`, log line, or `CollectionJob.self_test`. | Cross-ref `spec-tap-cares-secrets.md` redaction. |
| req-tap-cares-collector-self-test-14 | Skip Does Not Escalate | Proposed | A `skip` is informational; status derives only from `fail` / `warn`. Skip-only ⇒ `ready`. Implementation `check_skip` / `_derive_status` must align. | |
| req-tap-cares-collector-self-test-15 | v0 Single Ambient Configuration | Proposed | A self-test means "this collector with this configuration"; v0 has one ambient configuration the collector discovers itself (AWS = the one well-known secret). Per-configuration and tiered (pre-/post-config) self-tests are Backlog. | See Future. |
| req-tap-cares-collector-self-test-16 | Run Mode | Proposed | `CollectionJob` carries a run mode: `full` (phase 1 → phase 2 if runnable) or `self_test_only` (phase 1 → stop). A one-off readiness check is a `self_test_only` job; passing ⇒ `SUCCESSFUL` ("no collection performed"). | Subsumes the Administrivia Self-test button. |

## Run Collection Entry Point
----
RID: `req-tap-cares-collector-run-collection`
Status: `Proposed`

`run_collection(collector)` is the public callable that the collection system exposes for starting a collection. It is the **scheduler boundary**: callers (the Administrivia HTMX handler for manual runs; the now-implemented scheduler for automated runs) invoke `run_collection` and the collection system owns everything from that point — CollectionJob creation, HAS_COLLECTION_JOB linking, Django Task enqueueing, CollectorConfig assembly, and lifecycle bookkeeping.

#### Signature

```python
def run_collection(
    collector: Collector,
    *,
    caller_context: CallerContext | None = None,
    manual_run: bool = False,
    manual_run_source: str = "",
) -> CollectionJob:
    """Start a collection run for the given Collector.

    Performs, in order:
    1. Enforce concurrency policy (req-tap-cares-collector-concurrency, Backlog).
    2. Create a CollectionJob node via _create_node_internal
       (since CollectionJob is INTERNAL_ONLY), persisting `manual_run` and
       `manual_run_source` on the row.
    3. Create a HAS_COLLECTION_JOB edge from collector.entity to the new job
       via the service-layer create_edge.
    4. Build a CollectorConfig from the collector and job entity IDs.
    5. Enqueue the run_collector Django Task with the JSON-safe IDs.
    6. Return the CollectionJob in its post-enqueue state.

    With ImmediateBackend (v0 default), the returned job will already
    reflect the terminal task outcome. With a worker backend, the job
    will be READY or RUNNING depending on worker pickup latency.
    """
```

#### Manual run provenance

`caller_context` and manual-run metadata answer different questions:

- `caller_context` captures who or what authority initiated the request (user, system actor, etc.).
- `manual_run` is a boolean that records whether a human explicitly pushed a Run button or otherwise invoked a manual-execution path.
- `manual_run_source` is a short string identifier of the manual surface — e.g. `administrivia.run_button`, `administrivia.collector_detail`, `shell`. Empty when `manual_run` is `false`.

Manual runs (Administrivia run button today; future manual surfaces) call `run_collection(...)` with `manual_run=True` and an appropriate `manual_run_source`. Scheduler-triggered runs leave both at defaults — the scheduler-trigger relationship is the inbound `ScheduleFire --TRIGGERED_JOB--> CollectionJob` edge, which is the canonical scheduler-trigger record. A future API trigger source would extend the same pattern (e.g. an `api_run` flag or an analogous edge from an API trigger node).

Both fields are durable on `CollectionJob`. They are not passed as transient task arguments.

#### Responsibilities and boundaries

`run_collection` owns:

- CollectionJob node creation (via `_create_node_internal` since `CollectionJob.INTERNAL_ONLY = True`).
- Persisting `manual_run` / `manual_run_source` on the CollectionJob.
- HAS_COLLECTION_JOB edge creation (via `tap_grid.services.create_edge`).
- Django Task enqueueing.
- Returning the job in its post-enqueue state.

`run_collection` does **not** own:

- Deciding *when* to run — that's the scheduler's job (or the human pressing a Run button).
- Picking which collector — the caller passes a `Collector` instance.
- Anything that happens during `cls(config).run()` execution — that's the task body's job.

#### v0 callers

The intended steady-state caller is the future scheduler subsystem. Until that subsystem exists, the only permitted v0 caller is the Administrivia HTMX panel handler (per `spec-tap-cares-administrivia.md` → `req-tap-cares-administrivia-manual-run`). Direct calls from arbitrary plugin code are not permitted; the path is "create a scheduler trigger" (future) or "use the Administrivia handler" (v0).

**Current Deviation (v0).** The eventual flow is: scheduler creates a `ScheduledCollection` (or run-now trigger) → scheduler calls `run_collection`. The scheduler subsystem is not yet specced or built. In its absence the Administrivia HTMX panel handler calls `run_collection` directly. This deviation is intentional and temporary: the run_collection contract (signature, side effects, sole-writer invariant) does not change when the scheduler lands; only the upstream caller does. Tracked here so future readers see the gap explicitly rather than discovering it by surprise.

#### Concurrency

`run_collection` is the authoritative point for collector concurrency enforcement. When `req-tap-cares-collector-concurrency` lands, the guard fires here — before CollectionJob creation, so a rejected request never produces a grid mutation. Manual UI triggers, scheduler triggers, and future API triggers all converge on `run_collection` and therefore share one concurrency contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-run-collection-1 | Public Entry Point | Proposed | `run_collection(collector, *, caller_context=None, manual_run=False, manual_run_source="") -> CollectionJob` is the sole public callable for starting a collection. | Replaces the v0 internal `enqueue_collection` name. |
| req-tap-cares-collector-run-collection-2 | Service-Layer Routing | Proposed | All grid mutations performed by `run_collection` (CollectionJob create, HAS_COLLECTION_JOB create) route through the service layer or the trusted-internal create helper. No direct ORM writes for grid-managed types. | |
| req-tap-cares-collector-run-collection-3 | CollectionJob Internal Create | Proposed | `run_collection` is the sole legal creator of CollectionJob rows, using `_create_node_internal` (since CollectionJob is INTERNAL_ONLY). | |
| req-tap-cares-collector-run-collection-4 | Edge Through Service Layer | Proposed | The HAS_COLLECTION_JOB edge is created via `tap_grid.services.create_edge`. | |
| req-tap-cares-collector-run-collection-5 | Concurrency Chokepoint | Proposed | `run_collection` is where the future concurrency guard (`req-tap-cares-collector-concurrency`) fires; manual, scheduled, and future API triggers all share it. | |
| req-tap-cares-collector-run-collection-6 | Scheduler Is Caller, Not Owner | Proposed | The future scheduler subsystem invokes `run_collection`; it does not reach behind it to create CollectionJobs or enqueue tasks directly. | |
| req-tap-cares-collector-run-collection-7 | Administrivia Caller Permitted In v0 | Proposed | The Administrivia HTMX panel handler is the permitted v0 caller. The path migrates to scheduler-mediated triggering when the scheduler spec lands; `run_collection`'s contract does not change. | See `spec-tap-cares-administrivia.md` `req-tap-cares-administrivia-manual-run`. |
| req-tap-cares-collector-run-collection-8 | Post-Enqueue Return | Proposed | The function returns the CollectionJob in its post-enqueue state. Under ImmediateBackend the job reflects terminal status; under worker backends it reflects READY or RUNNING. | |
| req-tap-cares-collector-run-collection-9 | Manual Run Provenance | Implemented | `run_collection` persists `manual_run` and `manual_run_source` on the created CollectionJob. Scheduler-triggered runs leave both at defaults; the inbound `TRIGGERED_JOB` edge from `ScheduleFire` is the canonical scheduler record. | See `spec-tap-cares-scheduler.md` `req-tap-cares-scheduler-trigger-provenance`. |

## Collector Task Execution
----
RID: `req-tap-cares-collector-task-execution`
Status: `Refactoring`

Collector execution uses Django's Tasks API as the v0 execution contract.

The `run_collector` Django Task is enqueued **only** by `run_collection` (see [Run Collection Entry Point](#run-collection-entry-point)). No other code path in `tap_cares` or in plugins is permitted to call `run_collector.enqueue(...)` directly. The `run_collection` entry point is the chokepoint that owns CollectionJob creation and HAS_COLLECTION_JOB linking before the task is dispatched; bypassing it would create a CollectionJob-less task that has nowhere to record its lifecycle.

A task worker process executes the task outside the request-response lifecycle. The task resolves the on-grid `Collector`, resolves the registered collector class from `collector_registry`, builds `CollectorConfig`, instantiates the class, and calls `run()`. The task body owns CollectionJob lifecycle transitions — RUNNING at task start, SUCCESSFUL/FAILED at task end (see `req-tap-cares-collector-job-sole-writer`).

The Django Task receives only JSON-safe identifiers and execution data. v0 expected task inputs include:

- `collector_entity_id`
- `collection_job_entity_id`

The exact task payload may evolve when future collector-specific configuration is introduced, but task arguments must remain JSON-safe. Task execution should not receive live model instances or arbitrary Python objects from the web process.

This requirement follows the standard Django Tasks shape: Django provides task definition, queuing, validation, and task-result plumbing; a worker process provides actual background execution. v0 does not introduce a second collector subprocess underneath the Django task worker.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-task-execution-1 | Django Tasks API | Implemented | Collector execution is enqueued through Django's Tasks API. | `tap_cares.tasks.run_collector` is decorated with `@django.tasks.task(takes_context=True)`. |
| req-tap-cares-collector-task-execution-2 | Worker Process Boundary | Implemented | Collector `run()` executes in a task worker process rather than the web request process. | v0 uses `django.tasks.backends.immediate.ImmediateBackend` (synchronous for dev/test); switching to a worker backend changes only `TASKS["default"]["BACKEND"]`. |
| req-tap-cares-collector-task-execution-3 | JSON-Safe Task Args | Implemented | Collector task arguments are JSON-serializable and initially limited to identifiers such as collector and job entity IDs. | `run_collector(context, collector_entity_id: str, collection_job_entity_id: str)`. |
| req-tap-cares-collector-task-execution-4 | Resolve In Worker | Implemented | The worker resolves Collector state and collector class registration after task execution begins. | Inside `run_collector`: looks up Collector + CollectionJob via service-layer reads (or ORM for INTERNAL_ONLY types), then calls `get_collector(registry_key)`. |
| req-tap-cares-collector-task-execution-5 | No Nested Subprocess In v0 | Implemented | v0 does not require the task worker to spawn a second collector subprocess. | |
| req-tap-cares-collector-task-execution-6 | Enqueue Only Via run_collection | Proposed | `run_collector.enqueue(...)` is called only from `run_collection`. No other code path in `tap_cares` or in plugins enqueues the task directly. | Enforced by convention; bypassing `run_collection` would produce a CollectionJob-less task with no lifecycle record. |

## Collector Read Boundary
----
RID: `req-tap-cares-collector-read-boundary`
Status: `Refactoring`

Collector modules must not mutate TAP graph state through arbitrary write paths, and must not mutate `CollectionJob` at all.

Collectors gather data and perform collector-specific interpretation. The `run_collection` entry point and the `run_collector` task body own grid writes for job state, status, and accumulated outputs (see `req-tap-cares-collector-job-sole-writer`). Collector modules may read TAP state only through approved search/read surfaces.

The initial read path should favor TAP search APIs and service-layer read operations. This keeps collector reads aligned with future authorization, dimensions, and security policy work.

For collection results, the approved mutation path is the GRIFT import surface defined in [Collector GRIFT Import Surface](#collector-grift-import-surface). This is an explicit carve-out: collector modules may cause grid mutation by submitting a GRIFT batch through the approved import path — that submission writes Batch + entity rows to the grid through `grift_import`, but it does **not** write to the calling `CollectionJob`. References to the produced batches accumulate on the collector instance; at terminal state the task body links each produced `Batch` to the `CollectionJob` with a `PRODUCED_BATCH` edge (`tap_grid/specs/spec-grid-edge.md` `req-grid-edge-produced-batch`), not by `self.submit_grift(...)` itself and not via an embedded batch-ID field.

Collector modules should not import TAP models, call generic write services, call `write_batch()` directly, or otherwise bypass GRIFT import semantics. They must not mutate `CollectionJob` even through the helpers' previous signatures — the new helpers do not accept a `job` parameter and the helpers cannot reach a CollectionJob without one.

Because v0 collector code still runs as Python inside a Django task worker process, this requirement is initially a contract and design constraint rather than a full sandbox. Stronger enforcement is tracked in [Strict Collector Isolation](#strict-collector-isolation).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-read-boundary-1 | No Mutation Outside GRIFT | Implemented | Collector modules are prohibited by contract from directly creating, updating, or deleting TAP-managed nodes or edges outside the approved GRIFT import surface. | GRIFT import is the explicit exception (`CollectorBase.submit_grift`). |
| req-tap-cares-collector-read-boundary-2 | Approved Read Surfaces | Implemented | Collector modules read TAP state through approved search/read surfaces rather than ad hoc ORM access. | Contract; not enforced at runtime in v0 (see -5). |
| req-tap-cares-collector-read-boundary-3 | Runtime Owns Job Writes | Proposed | `run_collection` and the `run_collector` task body are the sole writers of `CollectionJob` rows. Collector modules cannot reach a CollectionJob through the helpers; collector results accumulate on the collector instance and are persisted by the task body. | See `req-tap-cares-collector-job-sole-writer`. |
| req-tap-cares-collector-read-boundary-4 | Future Auth Alignment | Implemented | Collector read design must remain compatible with future authorization and dimension-scoped security. | |
| req-tap-cares-collector-read-boundary-5 | Enforcement Gap Named | Implemented | The spec explicitly recognizes that v0 in-process Python cannot fully sandbox collector code. | |

## Collector GRIFT Import Surface
----
RID: `req-tap-cares-collector-grift-import`
Status: `Refactoring`

Collector result mutations must route through TAP's GRIFT import surface.

GRIFT import is the top-most exposed grid ingestion affordance for batch-shaped interchange. It sits above the lower-level service batch plumbing: the importer validates the GRIFT document, applies GRIFT batch identity and ordering rules, decides create-versus-replace behavior, handles importer diagnostics, and then executes the resulting service-layer write batch.

In v0, collector instances submit collected results through `CollectorBase.submit_grift(document)` — a method on the collector base class that calls the in-process `grift_import()` and accumulates the resulting batch IDs on the collector instance. The collector contract treats GRIFT import as the approved result submission boundary. Collector modules must not call lower-level mutation primitives such as `write_batch()`, node/edge write helpers, direct ORM saves, or direct `Entity` updates.

#### Batch identity, naming, and correlation

Every batch a collector submits MUST carry a meaningful, collector-set `name` and `description` on the GRIFT batch envelope — neither left blank nor auto-derived. The name should identify the producing collector and what was collected (e.g. `aws vpc-subnet — acct 1234…`); the description should give an operator enough context to understand the batch without opening it. `Batch.name` is required on replace (`Batch.REPLACE_REQUIRED`); TAP does not invent a good one, so the collector owns it.

`submit_grift` takes `(self, document)`, calls in-process `grift_import()`, and accumulates a reference to each resulting batch — its `batch_entity_id` and its `disposition` (`imported` or `skipped`) — on the collector instance. It does not take or mutate `CollectionJob`:

```python
# In CollectorBase
def submit_grift(self, document) -> GriftImportResult:
    result = grift_import(document, ...)
    self._produced_batches.extend(
        (b.batch_entity_id, "imported") for b in result.imported_batches
    )
    self._produced_batches.extend(
        (b.batch_entity_id, "skipped") for b in result.skipped_batches
    )
    return result
```

`self._produced_batches` is an instance-level accumulator (attribute name is an implementation detail). At terminal state the task body — the sole `CollectionJob` writer — creates one `CollectionJob --PRODUCED_BATCH--> Batch` edge per accumulated batch via the canonical `create_edge()` service path, stamping `disposition` on each edge. This mirrors how `run_collection` creates the `Collector --HAS_COLLECTION_JOB--> CollectionJob` edge. There is **no `CollectionJob.grift_batches` field**: produced batches are a graph relationship (`tap_grid/specs/spec-grid-edge.md` `req-grid-edge-produced-batch`), traversable rather than embedded.

#### Rejection contract (abort-by-default)

GRIFT validates and applies each batch **atomically**: one hard error
anywhere in a batch (a duplicate `entity_id`, a schema violation) rejects
the *entire* batch — nothing in it lands. A rejected batch appears in
**neither** `result.imported_batches` **nor** `result.skipped_batches`;
it exists only as entries in `result.errors`
(`result.counts.batches_imported == 0`). Because the accumulator above
only mirrors imported/skipped, a rejected batch is otherwise *invisible*
to the collector: zero produced batches, zero collector errors, a run
that reports success — silent total data loss. This was a real defect
(observed 2026-05-19: a duplicate edge rejected an entire AWS collection;
caught only by luck of a baseline). GRIFT upload is the defining
collector operation, so the safe behavior must be the **default**, not
opt-in per collector.

Therefore `submit_grift` takes `on_rejection: Literal["abort","return"]
= "abort"`:

- **`"abort"` (default).** If `result.errors` is non-empty, `submit_grift`
  records one structured error — code `GRIFT_BATCH_REJECTED`, a
  base-class log-site token, `message_data` carrying `error_count` and
  `batches_imported`, message naming the first few `code: message`
  issues — onto `self.results` via `record_error`, then raises
  `GriftRejectedError` (a `CollectorBase`-level exception). The
  `run_collector` task body already turns a raised collector exception
  into the standard `FAILED` terminal patch (`req-tap-cares-collector-
  failure-mode`); no per-collector code is required. The error contract
  is **uniform across every collector** — one code, one shape, one token
  — because it lives in the base, not in N hand-copied guards that drift.
- **`"return"` (explicit opt-out).** `submit_grift` returns the
  `GriftImportResult` unraised; the caller takes ownership of
  `result.errors`. This is for a multi-batch collector that wants
  partial-success semantics (GRIFT rejects per *batch*, so a 10-batch
  document can have 9 good + 1 rejected; aborting the run would discard
  the 9). It must be typed on purpose — the footgun is the opt-in, never
  the default.

```python
# In CollectorBase
def submit_grift(
    self, document, *, on_rejection="abort", ...
) -> GriftImportResult:
    result = grift_import(document, ...)
    self._produced_batches.extend(...)        # imported + skipped, as above
    if result.errors and on_rejection == "abort":
        self.record_error(_SITE_GRIFT_REJECTED, "GRIFT_BATCH_REJECTED",
                          "...nothing landed: <issues>", message_data={...})
        raise GriftRejectedError(...)
    return result
```

**Eyes-open rollout (non-negotiable).** Flipping the default to `abort`
will turn any *currently green-but-silently-rejecting* collector run
**red** — correctly: it surfaces pre-existing silent data loss, it does
not create it. When this lands, every existing collector (notably the
KSI collector, which predates the packaging convention —
`req-tap-cares-collector-packaging`) is run once; anything that goes red
was already broken and is reconciled deliberately, not treated as a
regression. Same discipline as the gate reconciliation: surfacing latent
silent failure is the goal, a surprise is not.

This **supersedes** the interim AGENTS Core Rule ("any `submit_grift`
caller must check `result.errors` and fail loud") and the per-collector
`GRIFT_BATCH_REJECTED` guard shipped in the `aws_core` boto3 collector —
once the base owns this, that guard is deleted (it collapses upward; one
source of truth). The aws_core guard was the proof-of-concept that
retires itself.

#### Job correlation

"Which batches did this run produce" is answered by traversing `CollectionJob --PRODUCED_BATCH--> Batch`, filtering the `disposition` edge property for imported vs skipped. A run that submitted nothing has no such edges. A failed run has edges only for batches actually produced before the failure — the task body creates edges from the same accumulator regardless of terminal status, so partial progress stays visible.

Future strict isolation may replace the in-process call with a TAP API result-submission endpoint. That endpoint preserves the same contract: collector code submits GRIFT with a named, described batch; TAP validates, authorizes, imports, records provenance via `PRODUCED_BATCH`, and returns structured import results.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-grift-import-1 | GRIFT Is Result Boundary | Implemented | Collector result mutations route through GRIFT import rather than ad hoc grid writes. | `CollectorBase.submit_grift` wraps `grift_import()`. |
| req-tap-cares-collector-grift-import-2 | v0 In-Process Import Allowed | Implemented | v0 collector execution uses in-process `grift_import()` through `CollectorBase.submit_grift`. | |
| req-tap-cares-collector-grift-import-3 | No Raw write_batch | Implemented | Collector modules do not call `write_batch()` or lower-level node/edge mutation helpers directly. | Contract; not enforced at runtime in v0. |
| req-tap-cares-collector-grift-import-4 | Method On CollectorBase | Implemented | `submit_grift` is a method on `CollectorBase` taking `(self, document)` rather than a free helper taking `(job, document)`. It does not receive or mutate `CollectionJob`. | Removes the v0-pre-refactor multi-writer pattern. |
| req-tap-cares-collector-grift-import-5 | Instance-Level Accumulator | Implemented | Each produced batch's `(batch_entity_id, disposition)` accumulates on the collector instance during the run. No mid-run `CollectionJob` writes. | `CollectorBase._produced_batches`; `submit_grift` extends it. |
| req-tap-cares-collector-grift-import-6 | PRODUCED_BATCH Correlation | Implemented | At terminal state the task body creates one `CollectionJob --PRODUCED_BATCH--> Batch` edge per accumulated batch via `create_edge()`, with `disposition` ∈ {`imported`,`skipped`}. There is no `CollectionJob.grift_batches` field. | Cross-ref `req-grid-edge-produced-batch`. `tap_cares.tasks._link_produced_batches`, called from both terminal paths. |
| req-tap-cares-collector-grift-import-8 | Collector Names Each Batch | Proposed | Every batch a collector submits carries a meaningful collector-set `name` and `description` on the GRIFT batch envelope; neither is left blank or auto-derived. | `Batch.name` is required on replace; TAP does not invent it. |
| req-tap-cares-collector-grift-import-7 | Future API Compatible | Implemented | The v0 contract remains compatible with replacing in-process import with an API-based GRIFT submission surface under strict isolation. | `submit_grift` takes a document and returns a `GriftImportResult`; replacing the in-process call with an API round trip changes only the helper internals. |
| req-tap-cares-collector-grift-import-9 | Abort On Rejection By Default | In Development | `submit_grift(..., on_rejection="abort")` is the default: a non-empty `result.errors` ⇒ `record_error("GRIFT_BATCH_REJECTED", …)` + `raise GriftRejectedError`. The defining collector operation is safe by default; no per-collector guard required. | Supersedes the interim AGENTS rule + the aws_core per-collector guard. |
| req-tap-cares-collector-grift-import-10 | Explicit Partial-Success Opt-Out | In Development | `on_rejection="return"` returns the `GriftImportResult` unraised for multi-batch collectors that own `result.errors` and want partial-success. The unsafe path is opt-in, never the default. | GRIFT rejects per batch, so multi-batch docs can partially succeed. |
| req-tap-cares-collector-grift-import-11 | Uniform Base-Owned Error Contract | In Development | The structured error (code `GRIFT_BATCH_REJECTED`, `message_data` shape, base-class log-site token) and `GriftRejectedError` live on `CollectorBase`, identical for every collector. The task body's existing failure-mode handling turns the raise into the standard `FAILED` patch. | One source of truth vs. N drifting copies. |
| req-tap-cares-collector-grift-import-12 | Eyes-Open Existing-Collector Rollout | In Development | When the `abort` default lands, every existing collector (notably KSI, `req-tap-cares-collector-packaging`) is run once; any newly-red run was already silently rejecting and is reconciled deliberately, not treated as a regression. | Surfacing latent silent data loss is the goal. |

## CollectionJob Model
----
RID: `req-tap-cares-collector-job-model`
Status: `Refactoring`

`CollectionJob` is the on-grid execution record for one collector run.

A `Collector` is the root/capability node. A `CollectionJob` is a subordinate run instance that records the current lifecycle state of one attempted execution of that collector. The job exists so humans, management surfaces, schedulers, and future agents can see that collector execution is happening on the grid rather than inside an invisible background subsystem.

`CollectionJob` must be implemented as a standard TAP-managed `BaseModel` node using the model-building skill at `tap_grid/skills/add-model/SKILL.md`. The model should follow ordinary TAP model conventions rather than re-specifying boilerplate in this requirement.

`CollectionJob` declares `INTERNAL_ONLY: ClassVar[bool] = True` per `req-grid-entity-internal`. Generic `create_node` / `patch_node` / `replace_node` / `delete_node` and GRIFT import all reject the `collection_job` entity type. The sole legal creator is `run_collection(...)` (see [Run Collection Entry Point](#run-collection-entry-point)), which uses `_create_node_internal` from `tap_grid.services`. The sole legal post-creation mutator is the `run_collector` task body (RUNNING transition at task start, terminal-state patch at task end); collector code never sees a CollectionJob handle — see [CollectionJob Sole-Writer Invariant](#collectionjob-sole-writer-invariant).

CollectionJob-specific model requirements:

- `CollectionJob` has a human-readable `name`.
- `CollectionJob` has a plain-text `description`.
- `CollectionJob` carries `manual_run` (bool, default `false`) and `manual_run_source` (string, default `""`) — see [Manual Run Provenance](#manual-run-provenance) below. Scheduler-triggered runs leave both at defaults; the scheduler-trigger relationship is recorded by the inbound `TRIGGERED_JOB` edge from `ScheduleFire`.
- `CollectionJob` has a `status` `CharField` driven by a `models.TextChoices` enum (see [CollectionJob Lifecycle Status](#collectionjob-lifecycle-status)).
- `CollectionJob` has a `task_result_id` `CharField(max_length=128, blank=True, default="")`. This stores the `TaskResult.id` returned by Django's Tasks API — a backend-defined string, **not** a UUID. The built-in `immediate` and `dummy` backends use 32-char random strings (`get_random_string(32)`); other backends may differ. `max_length=128` is comfortably above the current built-in but small enough to remain index-friendly. Empty string represents "not yet enqueued / enqueue raised."
- `CollectionJob` has `enqueued_at`, `started_at`, and `finished_at` `DateTimeField(null=True, blank=True)` timestamps; each is populated as the corresponding lifecycle transition occurs.
- `CollectionJob` has a `summary` `CharField(max_length=2048, blank=True, default="")` field for the at-a-glance one-liner describing what happened on this run — success or failure. Structured per-event detail (codes, messages, context) lives in `results` (below); `summary` is the human-facing single line that shows up wherever the job is summarized.
- `CollectionJob` has a `results` `JSONField` carrying the structured per-event log for this run (see [CollectionJob Results Log](#collectionjob-results-log) below).
- `CollectionJob` has **no** `grift_batches` field. Batches the run produced are linked by `CollectionJob --PRODUCED_BATCH--> Batch` edges (carrying a `disposition` property), created by the task body at terminal state — see `tap_grid/specs/spec-grid-edge.md` `req-grid-edge-produced-batch` and `req-tap-cares-collector-grift-import-6`. Produced batches are a graph relationship, not an embedded list.
- The `CollectionJob` display projection emits both the raw `status` value and a `status_display` field carrying the human-readable label (via Django's auto-generated `get_status_display()`).
- The v0 default dimension is `{"tap_cares": "collection_job"}`.

The job does not snapshot `Collector.collector_registry` in v0. The job's collector provenance comes from the `Collector --HAS_COLLECTION_JOB--> CollectionJob` edge. If immutable runner snapshots become necessary, that should be added as a separate requirement.

### CollectionJob Results Log

The `results` field is the structured per-event log for one collector run. It captures successes, warnings, and errors uniformly so consumers (UIs, audits, future Action rules) have a single place to read what happened.

#### Shape

```python
results = models.JSONField(default=_empty_results_dict, blank=True)

def _empty_results_dict() -> dict[str, list]:
    return {"info": [], "warn": [], "error": []}
```

Top-level shape is **pre-defined arrays per level**, never a flat list with embedded `level` fields. This keeps "show me errors" / "did anything warn?" as direct lookups (`results["error"]`) rather than filter operations, and keeps the JSON Schema strict — no level outside the three is permitted.

Per-entry shape (same for all three buckets):

```json
{
  "site":         "<hex>",
  "message_code": "<UPPER_SNAKE>",
  "message":      "<human-readable prose>",
  "message_data": { /* free-form */ }
}
```

| Field | Purpose |
| --- | --- |
| `site` | 4-hex call-site token (e.g. `a8f3`), minted via `scripts/log-site-id`. Identifies the line of code that emitted the entry; unique within its file (the file/module namespaces it). Grep the hex to locate the callsite. |
| `message_code` | Machine-readable category (`MASS_DELETION`, `UPSTREAM_OVERSIZED`, `RUN_COMPLETED`, …). Stable across runs and rewordings; what filtering and future Action rules key off, and the discriminator for `message_data`'s shape. |
| `message` | Human-readable prose for this run. Includes specifics (counts, ratios, offending fragments); `message_code` stays stable while `message` describes the particular occurrence. |
| `message_data` | Free-form structured payload. Empty object when none. Collector-defined keys; consumers treat unknown keys as opaque unless they recognize `message_code`. |

All four fields are **required** in stored entries. The pinned JSON schema (below) rejects entries missing any of them.

#### Unified message-object convergence

This per-entry shape is the grid-sink form of the canonical message object specified in [`spec-tap-logging.md`](../../specs/spec-tap-logging.md) (`req-tap-logging-message-object`). `site` / `message_code` / `message` / `message_data` are the same fields with the same meanings; the only difference is the sink — the log stream is ephemeral, `CollectionJob.results` is durable grid state. The optional envelope correlation fields of the message object (`entity_id`, `task_result_id`) are deliberately **not** duplicated per entry here: the parent `CollectionJob` row already *is* the grid subject and already carries `task_result_id`, so per-entry copies would be redundant. Same vocabulary, one place each fact lives.

#### Pinned schema

The shape is pinned at `tap_cares/schemas/collection_job_results.schema.json` per the JSON Schema Policy in `MEMORY.md`. The `record_*` helpers validate every entry against this schema before append; malformed entries raise rather than silently writing bad data.

#### Migration (rename to the unified vocabulary)

The field rename — `code`→`message_code`, `context`→`message_data`, and `site` from UUIDv7 to a 4-hex token — is a **clean cutover**, not a versioned migration. Verified: the pinned schema is enforced only at append time (`CollectorBase._record` → `_validate_entry`); nothing re-validates stored `CollectionJob.results` on read (the Administrivia run-detail reader is defensive — `isinstance` guard, `.get(level) or []`, no schema check). Combined with single-developer v0 and no production data, there is nothing to preserve: no transitional dual-accept regex, no data migration, no read-path throw risk on legacy rows. Existing dev-DB rows with the old field names are disposable; re-seed dev databases after the rename. (`scripts/uuid7` is no longer used to mint result `site` values; `scripts/log-site-id` is — UUIDv7 minting remains for entity IDs and GRIFT batch IDs.)

#### Service helpers

The result-recording helpers are **methods on `CollectorBase`**, not free functions, and they operate on instance-level accumulator state rather than on a `CollectionJob` row:

```python
class CollectorBase(ABC):
    def __init__(self, config: CollectorConfig) -> None:
        self.config = config
        self.results: dict[str, list] = {"info": [], "warn": [], "error": []}
        self._produced_batches: list[tuple[str, str]] = []  # (batch_entity_id, disposition)

    def record_info(self, site: str, message_code: str, message: str, *, message_data: dict | None = None) -> None: ...
    def record_warn(self, site: str, message_code: str, message: str, *, message_data: dict | None = None) -> None: ...
    def record_error(self, site: str, message_code: str, message: str, *, message_data: dict | None = None) -> None: ...
```

Each helper:

1. Builds the entry from the four arguments (defaulting `message_data` to `{}` if `None`).
2. Validates the entry against the pinned schema.
3. Appends to `self.results[<level>]`.

**No database write happens during `record_*`.** The accumulated `self.results` dict is persisted to `CollectionJob.results` by the task body in a single patch at terminal state (see [CollectionJob Sole-Writer Invariant](#collectionjob-sole-writer-invariant)). This is the structural fix that removes the v0-pre-refactor multi-writer / staleness pattern: there is exactly one writer to CollectionJob, and that writer reads from a single in-memory accumulator at the moment of write.

Collectors never manipulate `CollectionJob.results` directly; they always go through the helpers. `site` is **required positional** — forgetting it raises `TypeError`, which keeps every entry traceable to a single line of source.

The `tap_cares/results.py` module that previously exposed `record_info(job, ...)` free functions is being removed as part of the refactor.

#### Site token uniqueness

`site` follows the unified site-token rule (`req-tap-logging-site-ids` in `spec-tap-logging.md`): a 4-hex token that need only be unique **within its file**, because the module/file namespaces it. A repository-wide pytest scans every `self.record_info(…)` / `self.record_warn(…)` / `self.record_error(…)` call literal across collector subclasses and asserts no two callsites **in the same file** share a hex. Catches copy-paste mistakes at CI time. The test lives in `tap_cares/tests/test_results_site_uniqueness.py`; its invariant aligns with the logging scanner's within-file uniqueness check (`req-tap-logging-site-id-scanner-4`) — cross-file reuse is not a violation.

#### `summary` vs `results["error"]`

The two coexist with distinct roles:

- `summary` (CharField 2048) — the at-a-glance one-liner for a run (success or failure). Collectors set `self.summary` directly with whatever description fits ("Imported 46 indicators", "No changes", "Upstream returned malformed JSON"). When a collector fails without setting `self.summary`, the task body falls back to a count-derived `"Failed with N error(s)"`, then to the exception message. Renders wherever the job is summarized (Administrivia list, job detail header).
- `results["error"]` — the full structured detail. One entry per discrete error event, each with its own site / message_code / message_data. Renders in the per-run "what went wrong" view.

The summary intentionally hides per-message content; operators dig into `results["error"]` for specifics.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-job-model-1 | Standard BaseModel | Implemented | `CollectionJob` is specified as a normal TAP-managed `BaseModel` node implemented through the model-building skill conventions. | |
| req-tap-cares-collector-job-model-2 | Execution Record | Implemented | Each `CollectionJob` represents one attempted collector execution. | |
| req-tap-cares-collector-job-model-3 | Lifecycle Fields | Implemented | `CollectionJob` carries status, task result identity, lifecycle timestamps, and a bounded summary field. | |
| req-tap-cares-collector-job-model-4 | Default Dimension | Implemented | New CollectionJob nodes use the v0 default dimension `{"tap_cares": "collection_job"}`. | |
| req-tap-cares-collector-job-model-5 | No Registry Snapshot | Implemented | `CollectionJob` does not copy `Collector.collector_registry` in v0; the relationship to Collector carries that provenance. | |
| req-tap-cares-collector-job-model-6 | task_result_id Is String | Implemented | `task_result_id` is `CharField(max_length=128, blank=True, default="")` matching Django's `TaskResult.id: str` contract, not a UUID. Empty string indicates the task was not enqueued or enqueue raised. | |
| req-tap-cares-collector-job-model-7 | Bounded summary | Implemented | `summary` is bounded (CharField `max_length=2048`). Long traces and raw payloads are out of scope for this field and belong in the future status/log stream. | |
| req-tap-cares-collector-job-model-8 | Status Display Projection | Implemented | The CollectionJob display projection emits both the raw `status` value and a `status_display` field carrying the title-case human label from `get_status_display()`. | |
| req-tap-cares-collector-job-model-9 | Results Field Exists | Implemented | `CollectionJob` has a `results` `JSONField` defaulting to `{"info": [], "warn": [], "error": []}` (via a callable default helper). | |
| req-tap-cares-collector-job-model-10 | Pre-Defined Severity Buckets | Implemented | The top-level shape of `results` is three pre-defined arrays keyed `info` / `warn` / `error`. No flat-array form; entries never carry a `level` field (severity is implied by which bucket holds them). | |
| req-tap-cares-collector-job-model-11 | Four-Field Entry Shape | Implemented | Every result entry has exactly four required fields: `site` (4-hex token), `message_code` (UPPER_SNAKE), `message` (string), `message_data` (object). No other fields permitted. Converges on the unified message object (`req-tap-logging-message-object`). | Renamed from `code`/`context`; `site` is now a 4-hex token, not UUIDv7. |
| req-tap-cares-collector-job-model-12 | Pinned Results Schema | Implemented | The results shape is pinned at `tap_cares/schemas/collection_job_results.schema.json` with `additionalProperties: false` at both the top-level and per-entry. Field names match the unified message object in `spec-tap-logging.md`. | Clean cutover; see Migration note. |
| req-tap-cares-collector-job-model-13 | record_* Are Instance Methods | Proposed | The result-recording helpers are methods on `CollectorBase` (`self.record_info(site, message_code, message, *, message_data=None)` and the `warn` / `error` siblings). Each validates against the pinned schema and appends to `self.results[<level>]`. They do not accept a `CollectionJob` and do not write to the database. | Replaces the previous free-function shape in `tap_cares/results.py`. |
| req-tap-cares-collector-job-model-14 | Site Is Required Positional | Implemented | `site` is a required positional argument on the helpers. Calls missing it raise `TypeError` at runtime / fail type-checking, ensuring every stored entry traces to one line of source. | |
| req-tap-cares-collector-job-model-15 | Site Token Uniqueness Test | Implemented | A repository-wide pytest scans every `self.record_info` / `self.record_warn` / `self.record_error` callsite across collector subclasses and asserts no two **in the same file** share a `site` hex. Aligns with `req-tap-logging-site-id-scanner-4` (within-file uniqueness); cross-file reuse is not a violation. | `tap_cares/tests/test_results_site_uniqueness.py`. |
| req-tap-cares-collector-job-model-16 | summary Stays Distinct | Implemented | `summary` (CharField 2048) is the at-a-glance one-liner for a run (success or failure); structured per-event detail lives in `results["error"]`. The two are complementary, not redundant. | |
| req-tap-cares-collector-job-model-17 | INTERNAL_ONLY | Proposed | `CollectionJob.INTERNAL_ONLY = True`. Generic `create_node` / `patch_node` / `replace_node` / `delete_node` and GRIFT import all reject the `collection_job` entity type. | |
| req-tap-cares-collector-job-model-18 | run_collection Is Sole Creator | Proposed | The only legal path that creates a CollectionJob row is `run_collection(...)` (see [Run Collection Entry Point](#run-collection-entry-point)), which uses `_create_node_internal` from `tap_grid.services`. | |
| req-tap-cares-collector-job-model-19 | Accumulator Pattern For results | Proposed | The collector instance accumulates result entries in `self.results` during `run()`. The task body persists the accumulated dict to `CollectionJob.results` in a single patch at terminal state. No mid-run writes to the row. | Resolves the v0-pre-refactor staleness pattern. |
| req-tap-cares-collector-job-model-20 | Produced Batches Via Edge | Implemented | `CollectionJob` has no `grift_batches` field. Produced batches are linked by `PRODUCED_BATCH` edges (`disposition` ∈ {`imported`,`skipped`}) created by the task body at terminal state via `create_edge()`. | Supersedes the v0-pre-refactor embedded list; cross-ref `req-grid-edge-produced-batch`. `tap_cares.tasks._link_produced_batches`; field removed in migration 0010. |
| req-tap-cares-collector-job-model-21 | Manual Run Provenance | Implemented | `CollectionJob` carries `manual_run` (BooleanField, default `false`) and `manual_run_source` (CharField, default `""`) fields. Manual runs (Administrivia run button, future manual surfaces) set `manual_run=True` with a short source identifier. Scheduler-triggered runs leave both at defaults; the inbound `TRIGGERED_JOB` edge from `ScheduleFire` is the canonical scheduler-trigger record. See [Manual Run Provenance](#manual-run-provenance). | Replaces the earlier generic `trigger_source` / `trigger_description` framing per scheduler review feedback. |

## CollectionJob Sole-Writer Invariant
----
RID: `req-tap-cares-collector-job-sole-writer`
Status: `Proposed`

Exactly one piece of code mutates a `CollectionJob` row in a given run, and it does so in a small, predictable set of moments.

#### Writers

| Phase | Writer | Operation | Fields written |
| --- | --- | --- | --- |
| Run kickoff | `run_collection` | `_create_node_internal("collection_job", ...)` | `name`, initial `status` (`READY`), `enqueued_at`, default fields |
| Task start | `run_collector` task body | `_patch_node_internal` (or service-layer patch routed through `_create_node_internal`'s sibling for INTERNAL_ONLY types) | `status` (`RUNNING`), `started_at`, `task_result_id` |
| Task success | `run_collector` task body | one patch | `status` (`SUCCESSFUL`), `finished_at`, `summary`, `results`, `self_test` |
| Task failure | `run_collector` task body | one patch | `status` (`FAILED`), `finished_at`, `summary`, `results`, `self_test` |
| Terminal (either) | `run_collector` task body | `create_edge()` per produced batch | `CollectionJob --PRODUCED_BATCH--> Batch` edges, each stamped with `disposition` |

Three `CollectionJob`-row patches per run, total — none race. The task body holds no long-lived ORM instance across `collector.run()`; each patch is a fresh service-layer call. Terminal `PRODUCED_BATCH` edge creation is a separate service-layer operation by the same owner (`create_edge()`), not a `CollectionJob` row write — exactly as `run_collection`'s `HAS_COLLECTION_JOB` edge creation is not a row write.

#### What's not a writer

- Collector code is **not** a writer. It accumulates `self.results` and produced-batch references in-memory; the task body persists `results` / `self_test` and creates the `PRODUCED_BATCH` edges at terminal state.
- `record_info` / `record_warn` / `record_error` are **not** writers. They mutate `self.results` on the collector instance.
- `submit_grift` is **not** a writer of CollectionJob. It writes grid state through `grift_import` (which creates Batch + entity rows) and appends `(batch_entity_id, disposition)` to the collector instance's produced-batch accumulator. It does not touch the CollectionJob row; the `PRODUCED_BATCH` edges are created by the task body at terminal state.
- `enqueue_collection` is gone; its replacement `run_collection` is the kickoff writer, but it does not write to the row again after `.enqueue()` returns. The redundant post-enqueue `task_result_id` fallback that existed in v0-pre-refactor is removed; the task body writes `task_result_id` at task start.

#### Why this matters

The v0-pre-refactor code had at least seven write sites touching `CollectionJob` across four files, using `update_fields=[...]` as a poor man's column-level lock against a stale ORM instance held in `tasks.py` across the duration of `collector.run()`. The pattern worked under careful interleaving but fell apart under any scrutiny.

The sole-writer invariant replaces that pattern with a much simpler structural property: the task body owns the row, holds it for the minimum time required, persists everything else (results, self-test) from in-memory accumulators in one shot, and creates the `PRODUCED_BATCH` edges from the produced-batch accumulator. Read-modify-write windows are vanishingly small; staleness has nowhere to live.

#### One known limit

If the task itself dies hard (segfault, OOM, `kill -9`), neither terminal patch fires and the job sits at `RUNNING` forever. This is a Django Tasks reaping concern that exists for any task system; a separate "stuck job sweep" is the right answer and is out of scope for this requirement. The sole-writer invariant does not pretend to solve uncatchable process death.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-job-sole-writer-1 | Three Writes Per Run | Proposed | A normal run produces exactly three writes to the CollectionJob row: kickoff (READY), task start (RUNNING), task end (SUCCESSFUL or FAILED). | |
| req-tap-cares-collector-job-sole-writer-2 | Task Body Is Sole Mid/End Writer | Proposed | After `run_collection` returns, the only writer to the CollectionJob row is the `run_collector` task body. | |
| req-tap-cares-collector-job-sole-writer-3 | Collector Code Holds No Job Handle | Proposed | The collector instance has access to `self.config.collection_job_entity_id` (an ID) but never receives or fetches a CollectionJob instance. Helpers do not take a `job` parameter. | |
| req-tap-cares-collector-job-sole-writer-4 | Accumulators Persist At Terminal | Proposed | At terminal state the task body persists `self.results` → `CollectionJob.results` and `self_test` → `CollectionJob.self_test` in one patch, and creates `PRODUCED_BATCH` edges from the collector instance's produced-batch accumulator. | Edges via `create_edge()`, not a row write. |
| req-tap-cares-collector-job-sole-writer-5 | No update_fields Gymnastics | Proposed | The task body uses ordinary service-layer patches; no `update_fields=[...]` workarounds for concurrent writers, because there are no concurrent writers. | |
| req-tap-cares-collector-job-sole-writer-6 | No Long-Lived Stale Instance | Proposed | The task body does not hold a `CollectionJob` ORM instance across `collector.run()`. Each patch operates on a fresh service-layer round trip. | |
| req-tap-cares-collector-job-sole-writer-7 | Stuck-Job Reaping Out Of Scope | Proposed | Uncatchable task death (segfault, OOM, kill -9) is acknowledged as an unsolved case; a separate stuck-job sweep is the right fix and is out of scope. | |

## Collector HAS_COLLECTION_JOB Edge
----
RID: `req-tap-cares-collector-job-edge`
Status: `Implemented`

The relationship between a collector capability and a collection job is represented as:

```text
Collector --HAS_COLLECTION_JOB--> CollectionJob
```

This edge preserves the philosophical shape of the collector subsystem: `Collector` is the root capability node, and collection jobs are run instances owned by that collector.

tap-cares collector execution creates the `CollectionJob` node and the `HAS_COLLECTION_JOB` edge when it starts a collector run. Collector modules do not create this edge directly.

The `HAS_COLLECTION_JOB` edge should be a normal TAP edge type declared by tap-cares, with appropriate constraints so its source is `collector` and its target is `collection_job`.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-job-edge-1 | HAS_COLLECTION_JOB Edge Type | Implemented | tap-cares declares a `HAS_COLLECTION_JOB` edge type for Collector to CollectionJob relationships. | Registered programmatically in `TapCaresConfig.ready()` via `register_edge_type_constraints` (first-party apps don't use the plugin manifest). |
| req-tap-cares-collector-job-edge-2 | Direction | Implemented | The edge direction is `Collector --HAS_COLLECTION_JOB--> CollectionJob`. | |
| req-tap-cares-collector-job-edge-3 | Runtime Owned | Implemented | tap-cares collector execution creates the edge; collector modules do not create it directly. | Edge creation site lands with the orchestration service in Phase 5. |
| req-tap-cares-collector-job-edge-4 | Constrained Endpoints | Implemented | The edge type constrains source to `collector` and target to `collection_job`. | Strict rejection of disallowed endpoints depends on `tap_grid`'s Permission Union model: target node types must opt into `INBOUND_EDGES` constraints to actively block. The edge-type registration documents intended endpoints. |

## CollectionJob Lifecycle Status
----
RID: `req-tap-cares-collector-job-lifecycle`
Status: `Implemented`

`CollectionJob.status` reflects the coarse Django Tasks lifecycle for the collector task.

v0 intentionally maps `CollectionJob.status` directly to the Django task runner lifecycle because Django Tasks is the only supported collector runner process. If tap-cares later supports multiple runner backends, this requirement should be revisited so TAP-facing collection job status can be distinguished from backend-specific task status.

v0 status values mirror Django's `TaskResultStatus` exactly so no case translation is needed when copying status from a `TaskResult` to a `CollectionJob`. Values are stored uppercase; display labels are title-case:

```python
class Status(models.TextChoices):
    READY = "READY", "Ready"
    RUNNING = "RUNNING", "Running"
    FAILED = "FAILED", "Failed"
    SUCCESSFUL = "SUCCESSFUL", "Successful"
```

Stored values: `READY`, `RUNNING`, `FAILED`, `SUCCESSFUL`. Display labels: `Ready`, `Running`, `Failed`, `Successful`. The CollectionJob display projection exposes both (see `req-tap-cares-collector-job-model-8`).

The enum is tap-cares-owned — declared on `CollectionJob`, not imported from `django.tasks`. The v0 set deliberately mirrors Django's four values, but future TAP-specific states (`CANCEL_REQUESTED`, `CANCELLED`, `BLOCKED`, `PARTIAL`, etc.) are added by extending the local `TextChoices`, not by depending on Django's enum evolving.

tap-cares collector execution owns status updates. `run_collection` creates the job in `READY`. The `run_collector` task body transitions to `RUNNING` at task start and to `SUCCESSFUL` or `FAILED` at task end. These are the only writers — see [CollectionJob Sole-Writer Invariant](#collectionjob-sole-writer-invariant). The collector module class does not update job status directly and does not receive a CollectionJob handle.

TAP-specific states such as `CANCEL_REQUESTED`, `CANCELLED`, `BLOCKED`, or `PARTIAL` are deferred until concrete needs appear.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-job-lifecycle-1 | Django Status Values | Implemented | `CollectionJob.status` uses only `READY`, `RUNNING`, `FAILED`, and `SUCCESSFUL` (uppercase) in v0, matching `django.tasks.base.TaskResultStatus`. | |
| req-tap-cares-collector-job-lifecycle-2 | Runtime Updates Status | Implemented | tap-cares collector execution updates `CollectionJob.status` from task lifecycle changes. | Update site lands with the Django Tasks runtime in Phase 5. |
| req-tap-cares-collector-job-lifecycle-3 | Module Does Not Update Status | Implemented | Collector module classes do not directly mutate `CollectionJob.status`. | Enforced by contract: `CollectorBase.run` returns `None` and has no access to the `CollectionJob` instance. |
| req-tap-cares-collector-job-lifecycle-4 | Lifecycle Timestamps | Implemented | tap-cares records enqueued, started, and finished timestamps on the CollectionJob when available. | Timestamp-writing call sites land with the Django Tasks runtime in Phase 5. |
| req-tap-cares-collector-job-lifecycle-5 | TAP-Specific States Deferred | Implemented | TAP-specific job states are not part of v0 and require future requirements once tap-cares supports runner backends beyond the hardcoded Django task runner. | |
| req-tap-cares-collector-job-lifecycle-6 | TextChoices Enum | Implemented | `CollectionJob.status` is backed by a `models.TextChoices` enum with uppercase stored values and title-case display labels (`READY`/`"Ready"`, `RUNNING`/`"Running"`, `FAILED`/`"Failed"`, `SUCCESSFUL`/`"Successful"`). | |
| req-tap-cares-collector-job-lifecycle-7 | Enum Owned By tap-cares | Implemented | The Status enum is declared on `CollectionJob`, not imported from `django.tasks`. v0 mirrors Django's four values; future TAP-specific states extend the local enum rather than rely on Django's set evolving. | |

## Collector Failure Mode
----
RID: `req-tap-cares-collector-failure-mode`
Status: `Proposed`

How a collector signals a failed run is a framework convention, not a per-collector decision. Individual collectors specify *which conditions* trigger failure (their safety checks, threshold values, vocabulary of error codes) but they all use this single protocol to communicate failure to the runtime.

#### Failure protocol (collector side)

To fail a run, a collector:

1. Calls `self.record_error(site, message_code, message, *, message_data=...)` one or more times to accumulate structured error entries in `self.results["error"]`. Each entry traces to a specific source location via its 4-hex `site` token.
2. Raises a Python exception out of `run()`. The exception terminates the run; control returns to the task body, which writes terminal state.

Collectors may set `self.summary` with a human-readable description of what went wrong (e.g. "Upstream returned malformed JSON", "Mass-deletion threshold exceeded"). When the collector does not set `self.summary`, the task body derives a count-based fallback (`"Failed with N error(s)"`) from `self.results["error"]`, then falls back to the exception's class and message when no errors were recorded. The collector-set value wins whenever it is non-empty.

Whether *any particular* `record_error` call must be paired with a raise is a per-collector decision. Collectors are encouraged to accumulate every detectable error in a single pass (e.g. report all schema-drift sites in one run) and raise once at the end so the operator gets a complete picture. The framework's `record_error` does not auto-raise.

#### Failure protocol (runtime side)

The `run_collector` task body:

1. Catches any exception raised by `instance.run()`.
2. Writes a single FAILED-state patch to `CollectionJob` per `req-tap-cares-collector-job-sole-writer`: `status=FAILED`, `finished_at`, `summary` (collector-set `self.summary` if non-empty; otherwise derived from `len(results["error"])` as `"Failed with N error(s)"`; otherwise the exception's class and message), `results` (the full accumulator including all error entries), and `self_test` if phase 1 ran. It then creates `PRODUCED_BATCH` edges for whatever batches were produced before the abort (from the produced-batch accumulator).
3. Re-raises so Django Tasks' own failure machinery sees the failure.

#### What this guarantees

- Exactly one terminal-state write to `CollectionJob` per failed run.
- Structured failure detail (codes, messages, context, source sites) lives in `results["error"]`.
- At-a-glance failure summary lives in `summary` — either the collector-set string or a derived count (`"Failed with N error(s)"`) over the same accumulator.
- Both come from the same accumulator at the same write moment — no risk of `results["error"]` and `summary` disagreeing about what failed.

#### What this does not guarantee

- That a particular error code halts the run. That's per-collector policy; collectors signal "abort" by raising, not by calling `record_error`.
- That all collected results survive uncatchable process death (segfault, OOM, `kill -9`). The task body never runs in that case; the job sits at `RUNNING` until a future stuck-job sweep reaps it. See `req-tap-cares-collector-job-sole-writer-7`.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-failure-mode-1 | record_error + Raise Is The Protocol | Proposed | A collector fails a run by calling `self.record_error(...)` to accumulate structured detail and then raising an exception. The task body catches and persists. | |
| req-tap-cares-collector-failure-mode-2 | Single Terminal Write | Proposed | Failure produces exactly one terminal-state patch to `CollectionJob`, carrying status=FAILED plus the full accumulator. | See `req-tap-cares-collector-job-sole-writer`. |
| req-tap-cares-collector-failure-mode-3 | Failure summary precedence | Proposed | On failure the task body writes `summary` using this precedence: (1) collector-set `self.summary` if non-empty, (2) count-derived `"Failed with N error(s)"` from `len(results["error"])`, (3) the exception's class and message. Collectors that know what failed should set `self.summary` directly; the count-derived fallback covers collectors that just call `record_error` and raise. | Replaces the prior "count-always-wins" pattern; the collector now owns the summary on both success and failure. |
| req-tap-cares-collector-failure-mode-4 | Framework Does Not Auto-Halt | Proposed | `record_error` is a pure accumulator call; it does not raise. Per-collector policy decides whether a recorded error halts the run. | |
| req-tap-cares-collector-failure-mode-5 | Re-Raise For Task Backend | Proposed | The task body re-raises after writing FAILED state so Django Tasks' own failure machinery sees the failure. | |
| req-tap-cares-collector-failure-mode-6 | Plugin Specs Reference This | Proposed | Per-collector safety specs (KSI, future Emitter receivers, etc.) describe their own check vocabulary and policy but reference this requirement for the failure-signaling protocol instead of re-specifying mechanics. | |
| req-tap-cares-collector-failure-mode-7 | Collectors Set summary On Success | Implemented | Collectors should set `self.summary` near the end of a successful run with a human-readable one-liner describing what landed (counts, identifiers, "no changes"). The task body writes `self.summary` verbatim to `CollectionJob.summary` on the SUCCESSFUL terminal patch. Empty is allowed (the field stays blank in the UI) but discouraged. | Mirrors the failure-side precedence in `-3`; keeps the collector as the single source of truth for the summary on both outcomes. |

## Collection Job Status Messages And Logs
----
RID: `req-tap-cares-collector-job-logs`
Status: `Backlog`

Richer in-process job status messages, logs, warnings, and incremental progress events are deferred.

Django Tasks exposes coarse lifecycle information, but it does not provide a native progress/event stream for arbitrary task status messages. v0 therefore records coarse lifecycle state on `CollectionJob` and leaves detailed status/log emission for a later design.

Future work should define whether status messages and logs are modeled as separate grid nodes, edge-linked events, backend log records projected onto the grid, or a stricter isolated process message channel.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-job-logs-1 | Backlog Requirement Exists | Backlog | Rich collection job status/log/event emission is tracked as a named backlog requirement. | |
| req-tap-cares-collector-job-logs-2 | Not Required For v0 | Backlog | v0 collector execution is not required to emit incremental status messages or logs. | |
| req-tap-cares-collector-job-logs-3 | Future Grid Shape Required | Backlog | Future status/log work must define how messages become visible on the grid. | |

## Strict Collector Isolation
----
RID: `req-tap-cares-collector-strict-isolation`
Status: `Backlog`

Strict collector isolation is a future execution mode that enforces collector boundaries with operating-system or process-level controls.

The goal is to run collectors in an isolated environment that cannot mutate TAP graph state directly. A strictly isolated collector should receive serialized configuration, read TAP only through approved narrow APIs, and return through a validated result channel.

Possible implementation directions include:

- separate OS process per collector run
- distinct host user for collector execution
- restricted environment variables and credentials
- no Django database write credentials
- search-only TAP API token or equivalent read-only capability
- host-supported filesystem and network restrictions
- process-level kill controls

Strict isolation is not required for v0 collector execution. The v0 module and config contracts should, however, remain compatible with this future mode.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-strict-isolation-1 | Backlog Requirement Exists | Backlog | Strict collector isolation is tracked as a named backlog requirement. | |
| req-tap-cares-collector-strict-isolation-2 | No Write Credentials | Backlog | Isolated collectors do not receive Django database write credentials. | |
| req-tap-cares-collector-strict-isolation-3 | Approved Read Only | Backlog | Isolated collectors read TAP state only through approved search/read surfaces. | |
| req-tap-cares-collector-strict-isolation-4 | Serialized Config | Backlog | Isolated collectors receive JSON-safe serialized configuration. | |
| req-tap-cares-collector-strict-isolation-5 | Validated Return Channel | Backlog | Isolated collector output returns through a validated channel owned by tap-cares. | |
| req-tap-cares-collector-strict-isolation-6 | Kill Controls Considered | Backlog | Strict isolation design includes process-level termination controls or explicitly rejects them with rationale. | |

## Shared Collector Runtime Helpers
----
RID: `req-tap-cares-collector-runtime-helpers`
Status: `Backlog`

Standard collector tasks — cloning a git repo, fetching a URL, unpacking an archive, parsing a known file format — should be available as shared helpers so each new collector does not reimplement them. The Collector Module Class spec already nods at this direction ("Reusable behavior belongs in tap-cares collector runtime helpers and shared base classes, not in plugin-specific factory setup"); this requirement names the surface and defers its construction until concrete duplication appears.

The proposed shape is composition-first, not inheritance:

- Helpers live in a `tap_cares/helpers/` package, one module per concern (e.g. `git.py`, `http.py`, `archive.py`).
- Collectors discover helpers through ordinary Python imports (`from tap_cares.helpers.git import clone`). No registry — helpers are utilities, not pluggable interfaces, and do not need to be addressable from grid data the way collectors are.
- Helpers are functions returning small dataclasses. No singletons, no module-level state.
- Helpers accept what they need as keyword arguments (tmpdir paths, log sinks, secrets, retry policy) rather than reaching into a global context.

Plugin-local helpers may live in `plugins/<slug>/helpers/`. They graduate to `tap_cares/helpers/` when a second collector needs the same capability. This "wait for N=2" discipline keeps the shared surface small and grounded in real reuse.

An open design question that this requirement deliberately defers: whether collectors should receive a `CollectorContext` object that bundles tmpdir lifecycle, a log sink that feeds `CollectionJob.results`, secret resolution, and retry/rate-limit policy. The first two helpers (likely `git.clone` and `http.fetch`) should accept raw kwargs; the context shape, if it materializes, should be crystallized only after three concrete collectors agree on what they actually need passed in.

This work is explicitly **not blocking v0**. The first concrete collector (FedRAMP 20x KSI) hardcodes its behavior; helpers become valuable when the second and third collectors arrive and start duplicating each other. Until then, prefer copy-paste over premature abstraction.

A subclass-based `CollectorBase` extension (e.g. a `GitCollectorBase` that owns clone + checkout lifecycle) is explicitly **not** the v0 direction. Inheritance designed off a single concrete collector tends to misfit the next one; the helper-composition path stays open to crystallizing into a base class later, but does not force the shape early.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-collector-runtime-helpers-1 | Backlog Requirement Exists | Backlog | Shared collector runtime helpers are tracked as a named backlog requirement. | |
| req-tap-cares-collector-runtime-helpers-2 | Helpers Package Location | Backlog | Shared collector helpers live in `tap_cares/helpers/`, one module per concern (e.g. `git.py`, `http.py`, `archive.py`). | |
| req-tap-cares-collector-runtime-helpers-3 | Plain Import Discovery | Backlog | Collectors discover helpers through ordinary Python imports. No registry, no scope:key lookup, no grid-driven helper resolution. | |
| req-tap-cares-collector-runtime-helpers-4 | Function-First Shape | Backlog | Helpers are functions returning small dataclasses. Reusable subclass bases of `CollectorBase` are not added until at least three concrete collectors demonstrate a shared lifecycle. | |
| req-tap-cares-collector-runtime-helpers-5 | Kwargs Not Globals | Backlog | Helpers accept tmpdir paths, log sinks, secrets, and policy via keyword arguments rather than reaching into a shared global or module-level context. | |
| req-tap-cares-collector-runtime-helpers-6 | CollectorContext Deferred | Backlog | A bundled `CollectorContext` object passed into collectors is explicitly deferred until at least three concrete collectors agree on its contents. | |
| req-tap-cares-collector-runtime-helpers-7 | Promotion On Reuse | Backlog | Plugin-local helpers in `plugins/<slug>/helpers/` are promoted to `tap_cares/helpers/` only when a second collector adopts them. | |
| req-tap-cares-collector-runtime-helpers-8 | Not Required For v0 | Backlog | v0 collector execution is not required to use or provide shared helpers. The first concrete collector (FedRAMP 20x KSI) hardcodes its behavior. | |

## Future

- Define collection job status/log/error nodes and edges beyond coarse lifecycle status.
- Define richer collection result records and job-to-batch graph relationships.
- Define management surfaces for collectors and collection jobs.
- Build out shared collector runtime helpers once a second concrete collector demonstrates the duplication pattern (see [Shared Collector Runtime Helpers](#shared-collector-runtime-helpers)).
