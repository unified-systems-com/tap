# tap-cares Task Backend Specification

## Philosophy

TAP runs background work — collector executions, the once-per-minute scheduler clock, and future async ingestion or API-triggered work — through Django's built-in `django.tasks` framework (DEP 0014). The backend implementation is replaceable; the contract is what matters.

v0 used `ImmediateBackend` (synchronous, same-thread) as a dev placeholder. The scheduler subsystem makes the limitation concrete: `evaluate_tick` invokes `run_collection` which blocks until the collector finishes, so a slow collector lags the clock. Production-equivalent semantics — `CollectionJob.status` actually transitioning READY → RUNNING → SUCCESSFUL over wall-clock time, scheduler ticks not blocked on collector execution — require a real worker backend.

This spec defines the v0+ task-backend choice (Steady Queue), the worker and queue topology, the test ergonomics, the deployment model, and the relationship to TAP's on-grid scheduler. TAP-owned scheduling concepts (`Schedule`, `ScheduleFire`, `evaluate_tick`) are unchanged — the backend is infrastructure underneath them, not a substitute for them.

The architectural line:

| Layer | Lives in | Owner |
| --- | --- | --- |
| Cron policy (what runs when) | `Schedule` on the TAP grid | Operators (GRIFT, admin UI) |
| Fire history / decisions | `ScheduleFire` on the TAP grid | Scheduler service |
| Slot evaluation | `evaluate_tick` in `tap_cares.scheduler` | Scheduler service |
| Periodic clock | `@recurring` task in Steady Queue | Infrastructure |
| Job execution | `@task` functions in Steady Queue workers | Infrastructure |

The bottom two rows are replaceable. Everything users edit lives on the grid.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Production-Equivalent | `CollectionJob` lifecycle transitions over wall-clock time, matching what operators will see in prod |
| 2. | Isolated     | Scheduler clock cannot be starved by collector execution backlog |
| 3. | Postgres-Only | No Redis or queue server in the dev or prod footprint |
| 4. | Test-Friendly | Existing tests that rely on synchronous task completion keep working |
| 5. | Grid-Authoritative | TAP's `Schedule` entity remains the canonical recurring policy store; the backend's own `@recurring` mechanism is used for exactly one task (the TAP scheduler tick) |
| 6. | Replaceable  | Depend on the `django.tasks` `TaskBackend` interface, not on backend specifics |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-task-backend-steady-queue | [Steady Queue](#steady-queue) | Implemented | Steady Queue is the v0 production-equivalent backend |
| req-tap-cares-task-backend-django-tasks-interface | [Django Tasks Interface](#django-tasks-interface) | Implemented | TAP code uses only the DEP 0014 `@task` decorator and the `TASKS` settings dict |
| req-tap-cares-task-backend-queue-isolation | [Queue Isolation](#queue-isolation) | Implemented | Scheduler tick runs on a dedicated queue with its own worker pool |
| req-tap-cares-task-backend-transactional-integrity | [Transactional Integrity](#transactional-integrity) | Implemented | `run_collection` uses `transaction.on_commit` to defer enqueue past any outer transaction |
| req-tap-cares-task-backend-test-settings | [Test Settings](#test-settings) | Implemented | Tests use `ImmediateBackend` to preserve synchronous-completion semantics |
| req-tap-cares-task-backend-recurring-scope | [Recurring Scope](#recurring-scope) | Implemented | Steady Queue's `@recurring` is used ONLY for the TAP scheduler tick |
| req-tap-cares-task-backend-deployment | [Deployment](#deployment) | Implemented | Steady Queue supervisor runs in the web container alongside Django |
| req-tap-cares-task-backend-fork-safety | [Fork Safety](#fork-safety) | Implemented | Forked workers handle Django DB connections correctly |
| req-tap-cares-task-backend-huey-removal | [Huey Removal](#huey-removal) | Implemented | Huey is removed from settings, deps, and infrastructure as part of this refactor |
| req-tap-cares-task-backend-migration-plan | [Migration Plan](#migration-plan) | Implemented | Two-step rollout: backend swap first, then Huey replacement |
| req-tap-cares-task-backend-backlog | [Backlog](#backlog) | Backlog | Multi-machine workers, alternative backends, observability surfaces |

## Steady Queue
----
RID: `req-tap-cares-task-backend-steady-queue`
Status: `Implemented`

Steady Queue (a Python port of Rails' Solid Queue) is the v0 production-equivalent task backend. It is a drop-in implementation of the `django.tasks` `TaskBackend` interface, and ships its own cron-style scheduler via the `@recurring` decorator.

TAP configures Steady Queue on Postgres — the same database TAP already runs — so the task backend introduces no new infrastructure. Steady Queue uses `FOR UPDATE SKIP LOCKED` for lock-free polling on Postgres and MySQL 8+. Upstream also supports MySQL and SQLite, but TAP standardizes on Postgres.

Chosen because:

- Implements the standard `django.tasks` `TaskBackend` interface — no parallel runtime, the swap is `settings.TASKS` plus a worker process.
- PostgreSQL-only storage — no new infrastructure beyond the database we already run.
- Solid Queue heritage — battle-tested design even though the Python port is younger.
- Built-in `@recurring` decorator — lets us replace Huey's periodic-task role with the same backend, collapsing two task systems into one.

Known limitations (from upstream docs) that we accept:

- **No `task.return_value` result fetching.** TAP collectors already persist their outcome on `CollectionJob.results`, `summary`, and `self_test`, plus `CollectionJob --PRODUCED_BATCH--> Batch` edges (there is no `CollectionJob.grift_batches` field — `req-tap-cares-collector-grift-import-6`); the v0 collector contract doesn't rely on synchronous return values.
- **POSIX-only (fork-based concurrency).** Acceptable — TAP runs in Linux containers.
- **No async task enqueueing.** We don't use async enqueue.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-steady-queue-1 | Selected Backend | Implemented | `steady_queue.backend.SteadyQueueBackend` is the configured `TASKS["default"]["BACKEND"]` in dev and prod settings. | |
| req-tap-cares-task-backend-steady-queue-2 | Dependency Added | Implemented | `steady_queue` is added through `uv` and declared in `pyproject.toml`. | |
| req-tap-cares-task-backend-steady-queue-3 | Installed App | Implemented | `steady_queue` is in `INSTALLED_APPS` so its migrations apply. | |
| req-tap-cares-task-backend-steady-queue-4 | Migrations Applied | Implemented | The container entrypoint's `manage.py migrate` step applies Steady Queue's tables alongside TAP's. | |

## Django Tasks Interface
----
RID: `req-tap-cares-task-backend-django-tasks-interface`
Status: `Implemented`

TAP code only uses the DEP 0014 `@task` decorator from `django.tasks` and the `TASKS` settings dict to configure backends. No TAP module imports Steady Queue classes or types beyond the settings file and the (single) `@recurring` declaration.

This keeps the backend swap surface tiny: replacing Steady Queue later (e.g. with a Redis-backed alternative) is a settings change plus possibly a different process invocation, not a TAP-wide refactor.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-django-tasks-interface-1 | Task Definitions Unchanged | Implemented | `run_collector` and other `@task`-decorated functions in `tap_cares/tasks.py` are unchanged by this refactor. | |
| req-tap-cares-task-backend-django-tasks-interface-2 | No Backend Imports In TAP | Implemented | No file outside `tap/settings.py` and the recurring-tick module imports `steady_queue`. | One concession: the recurring-tick declaration uses `@recurring` from `steady_queue.recurring_task`. That import is the documented exception. |
| req-tap-cares-task-backend-django-tasks-interface-3 | Replaceable Backend | Implemented | Swapping Steady Queue for another DEP 0014 backend is a settings + process change, not a TAP code change. | |

## Queue Isolation
----
RID: `req-tap-cares-task-backend-queue-isolation`
Status: `Implemented`

The scheduler tick runs on a **dedicated queue** with its **own worker pool**. A backlog of collector tasks cannot delay the once-per-minute clock.

Concrete v0 topology:

```python
# settings.py
STEADY_QUEUE = Configuration.Options(
    workers=[
        Configuration.Worker(queues=["scheduler"], threads=1),
        Configuration.Worker(queues=["default"],   threads=3),
    ],
)
```

- **`scheduler` queue, 1 thread**: only the once-per-minute scheduler tick runs here. Tick is fast (<1s); one thread is sufficient.
- **`default` queue, 3 threads**: collectors and any other background work. Three threads allow modest collector parallelism while leaving the host responsive.

The scheduler tick is tagged with `queue_name="scheduler"` on its `@recurring` declaration. All other `@task`-decorated work defaults to the `default` queue and so lands on the collector-pool worker. No third queue is introduced in v0; collectors share the default queue with everything else that isn't the clock.

The supervisor forks one worker process per `Worker` configuration, so the two workers are truly isolated at the OS-process level. A blocked or runaway collector affects only the default worker's thread pool; the scheduler worker keeps polling.

### When to revisit `threads=3`

The default worker's thread count is a v0 guess. Concrete signals that we need to revisit:

- **Pickup latency.** Every `CollectionJob` already records `enqueued_at` and `started_at`; the difference is queue-pickup latency. If the p95 of `started_at - enqueued_at` for the default queue exceeds ~30 seconds over a representative period, the worker pool is undersized. The Administrivia run-history surface already shows these timestamps; an operational query against `CollectionJob` would surface the heuristic.
- **Persistent `READY` backlog.** Jobs accumulating in `CollectionJobStatus.READY` while host CPU is idle is the direct symptom. Either the worker pool is undersized or the polling interval is too long.
- **Operator-perceived latency.** "I clicked Run and it took N seconds to start" is a real signal; if the Administrivia surface starts feeling sluggish to operators, the worker pool is part of the diagnosis.
- **Scheduler tick lag.** Although the scheduler is on its own isolated worker, a `ScheduleFire` whose `fired_at` is consistently later than `scheduled_for + a few seconds` hints at a different issue (Steady Queue dispatcher pressure, host load), not collector workers. Distinguishing the two signals is part of the diagnosis.

Revising the thread count is a settings change with no schema or behavioral implications, so the bar for revisiting is intentionally low: when the symptoms above show up, bump the number and re-measure.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-queue-isolation-1 | Dedicated Scheduler Queue | Implemented | The TAP scheduler tick is tagged `queue_name="scheduler"`. | |
| req-tap-cares-task-backend-queue-isolation-2 | Dedicated Scheduler Worker | Implemented | `STEADY_QUEUE` configuration declares a `Worker` with `queues=["scheduler"]` separate from the default-queue worker. | One thread is sufficient for v0. |
| req-tap-cares-task-backend-queue-isolation-3 | Collectors On Default Queue | Implemented | `run_collector` and other collector-execution tasks are NOT tagged with a queue and therefore run on the `default` queue worker. | |
| req-tap-cares-task-backend-queue-isolation-4 | OS-Level Isolation | Implemented | The two queue workers run in separate forked processes under one supervisor; no thread-level sharing between scheduler and default queues. | Guaranteed by Steady Queue's supervisor model. |
| req-tap-cares-task-backend-queue-isolation-5 | Thread-Count Revisit Trigger | Implemented | The default worker's thread count is revisited when p95 of (`CollectionJob.started_at` - `CollectionJob.enqueued_at`) exceeds ~30 seconds, or when `READY` jobs persistently accumulate while host CPU is idle, or when operator-perceived run-button latency becomes a complaint. | Settings change only — no schema or behavioral implications, low bar for revisiting. |

## Transactional Integrity
----
RID: `req-tap-cares-task-backend-transactional-integrity`
Status: `Implemented`

Steady Queue stores task rows in the same Postgres database that holds `CollectionJob`, `Schedule`, `ScheduleFire`, and the rest of the TAP grid. That coupling is desirable — no second store to keep in sync — but it introduces a subtle hazard around transactional ordering.

The hazard: if `run_collection(...)` is called inside an uncommitted outer `transaction.atomic()` block, `.enqueue()` inserts a row into `steady_queue_ready_executions` *inside that same transaction*. A Steady Queue worker polling on a different DB connection cannot see the new task row until the outer transaction commits — and the `CollectionJob` row + `HAS_COLLECTION_JOB` edge that the task body looks up are also not committed yet. In a race between worker pickup and outer commit, the worker can pick up a task whose row data is not yet visible, producing spurious lookup failures.

**Mitigation in TAP**: `run_collection` wraps the `.enqueue()` call in `django.db.transaction.on_commit(...)` so the enqueue is deferred until the outermost transaction commits. When there is no outer transaction (the current state for the Administrivia run-button handlers and the scheduler tick Stage 2), `on_commit` fires the callback immediately — so existing call sites see no behavioral change. When there IS an outer transaction (a future caller wrapping multiple service calls in an atomic block), the enqueue correctly waits for the commit.

This keeps the contract simple: callers do not need to know about transaction state. `run_collection` does the right thing regardless.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-transactional-integrity-1 | on_commit Wrapping | Implemented | `run_collection` wraps `run_collector.enqueue(...)` in `django.db.transaction.on_commit(...)`. | Defers the enqueue until any outer transaction commits; fires immediately if none. Positively guarded by `tap_cares/tests/test_task_execution.py::TestTransactionalIntegrity` (asserts the collector does not run inside an open outer `atomic()` and does run after it commits; the test fails if the wrap is removed). |
| req-tap-cares-task-backend-transactional-integrity-2 | Caller Contract | Implemented | Callers of `run_collection` do not need to inspect transaction state; the function is safe both inside and outside an outer `transaction.atomic()` block. | |
| req-tap-cares-task-backend-transactional-integrity-3 | No Behavior Change For Current Callers | Implemented | Wrapping in `on_commit` does not change behavior for current callers (Administrivia handlers, scheduler Stage 2) because none of them run inside an outer atomic block. | The deferral mechanism itself is positively guarded by `TestTransactionalIntegrity` (see -1). The narrower "no current caller runs inside an outer `atomic()`" claim remains a code-inspection inference, not a separate assertion — acceptable because the failure mode is benign (the wrap fires immediately when there is no outer transaction). |
| req-tap-cares-task-backend-transactional-integrity-4 | Test Marker For Lifecycle Assertions | Implemented | Tests that exercise `run_collection` and assert post-task `CollectionJob` state use `@pytest.mark.django_db(transaction=True)`. The default `@pytest.mark.django_db` wrapper runs each test inside an atomic block that rolls back at end-of-test, so `on_commit` callbacks would never fire under ImmediateBackend. | Standard Django pattern when production uses `transaction.on_commit`. |

## Test Settings
----
RID: `req-tap-cares-task-backend-test-settings`
Status: `Implemented`

Tests use `ImmediateBackend` for `TASKS["default"]["BACKEND"]` so synchronous-completion semantics are preserved. Existing tests (`test_task_execution.py`, `test_scheduler.py::TestEvaluateTickTriggered`, etc.) assume the `CollectionJob` is in its terminal state by the time `run_collection` returns — that assumption is correct under `ImmediateBackend` and is preserved.

Implementation: a separate `tap/test_settings.py` module imports from `tap/settings.py` and overrides `TASKS` (and any other test-only overrides). `pytest-django` is configured via `pyproject.toml` / `pytest.ini` to use `DJANGO_SETTINGS_MODULE=tap.test_settings`; the container entrypoint and management commands continue to default to `DJANGO_SETTINGS_MODULE=tap.settings`.

Cleanest separation: easiest to grep, no env-var flag conditionals in `settings.py`, and `pytest-django` supports it out of the box.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-test-settings-1 | Tests Use ImmediateBackend | Implemented | `pytest` invocation uses `tap/test_settings.py` where `TASKS["default"]["BACKEND"]` is `django.tasks.backends.immediate.ImmediateBackend`. | |
| req-tap-cares-task-backend-test-settings-2 | Existing Tests Unchanged | Implemented | No test file requires modification to keep passing under this refactor. Tests that rely on synchronous task completion continue to work. | |
| req-tap-cares-task-backend-test-settings-3 | Dev / Prod Use Steady Queue | Implemented | `scripts/dc up` (and any production deploy) configures `TASKS["default"]["BACKEND"]` as `steady_queue.backend.SteadyQueueBackend` via `tap/settings.py`. | |
| req-tap-cares-task-backend-test-settings-4 | Test Settings Inherit | Implemented | `tap/test_settings.py` imports from `tap/settings.py` and overrides only the test-relevant values (`TASKS`, etc.); it does not re-declare the full settings surface. | Keeps settings drift between dev and test minimal. |
| req-tap-cares-task-backend-test-settings-5 | pytest-django Configured | Implemented | `pyproject.toml` (or `pytest.ini`) sets `DJANGO_SETTINGS_MODULE = "tap.test_settings"` for pytest discovery. | |

## Recurring Scope
----
RID: `req-tap-cares-task-backend-recurring-scope`
Status: `Implemented`

Steady Queue's `@recurring` decorator is used for **exactly one** task: the TAP scheduler tick. **This is a hard rule, not a v0 starting point.** No future TAP work introduces additional `@recurring` declarations.

Why this matters: `@recurring` is code-driven (the schedule is declared at function definition time and persisted by Steady Queue in its own `steady_queue_recurringexecution` table). TAP's `Schedule` is data-driven (operators create them via GRIFT or the admin UI, scheduler edits modify them, fire history lives on the grid). Pushing TAP schedules into `@recurring` would lose operator visibility, GRIFT-seedability, and admin-page editability.

If a future need looks like "we should run task X on a schedule", the answer is **always** "create an on-grid `Schedule` whose target is X" — not "add a second `@recurring` decorator". The `@recurring` mechanism is plumbing for exactly the once-per-minute TAP scheduler tick; everything else routes through the grid-authoritative `Schedule` entity (`req-tap-cares-task-backend-recurring-scope-2`).

The single recurring declaration replaces the Huey periodic task:

```python
# tap_cares/task_backend.py (new module, replaces tap_cares/huey_tasks.py)
from django.tasks import task
from steady_queue.recurring_task import recurring

@recurring(schedule="* * * * *", key="tap_scheduler_tick", queue_name="scheduler")
@task()
def scheduler_tick() -> None:
    from tap_cares.scheduler import evaluate_tick
    evaluate_tick()
```

`steady_queue_recurringexecution` ends up with exactly one row: `tap_scheduler_tick`. Everything else operators see and edit lives on the TAP grid.

### Enforcement

A repository-wide pytest scans `tap_cares/`, `tap_*/`, and `plugins/` for `@recurring(` callsites and asserts exactly one match — the TAP scheduler tick. Same pattern as `tap_cares/tests/test_results_site_uniqueness.py`, which enforces a single-site-uuid invariant across collector callsites.

This makes the rule self-enforcing: a contributor who adds a second `@recurring` will see the test fail with a pointer to this spec section, before the code lands.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-recurring-scope-1 | Single Recurring Task | Implemented | The codebase declares exactly one `@recurring`-decorated task: the TAP scheduler tick. **Hard rule, not a v0 starting point.** Future scheduling needs use the on-grid `Schedule` entity instead. | |
| req-tap-cares-task-backend-recurring-scope-2 | Schedule Stays Grid-Authoritative | Implemented | TAP `Schedule` entities are not migrated to or duplicated in Steady Queue's recurring-task table. New scheduled work always routes through `Schedule`. | |
| req-tap-cares-task-backend-recurring-scope-3 | Tick Defers To evaluate_tick | Implemented | The recurring task body's only logic is `evaluate_tick()`; no inline scheduler decisions. | |
| req-tap-cares-task-backend-recurring-scope-4 | Test Enforces Single Recurring | Implemented | A repository-wide pytest scans for `@recurring(` callsites and asserts exactly one match. | Mirrors `test_results_site_uniqueness.py`. |

## Deployment
----
RID: `req-tap-cares-task-backend-deployment`
Status: `Implemented`

Steady Queue's supervisor runs alongside the Django dev server inside the existing web container. Same pattern the Huey consumer follows today: `docker/entrypoint.sh` backgrounds `manage.py steady_queue` before `exec`-ing into the dev server (`runserver_nocache` — the no-store-static dev variant of `runserver`), with a `trap` to clean up on exit.

This preserves the one-container dev story (no separate compose service) and inherits the same caveats: Steady Queue does NOT auto-reload on file changes; restart the container after editing task code.

Future production deployments may move Steady Queue to a separate container or host for resource isolation. The settings contract (`TASKS["default"]["BACKEND"]` + `STEADY_QUEUE` config) is unchanged; only the process invocation moves.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-deployment-1 | In-Container Supervisor | Implemented | `docker/entrypoint.sh` starts `manage.py steady_queue` as a background process in the web container. | |
| req-tap-cares-task-backend-deployment-2 | Trap Cleanup | Implemented | The entrypoint's exit trap kills the Steady Queue supervisor when the container stops. | |
| req-tap-cares-task-backend-deployment-3 | No Auto-Reload | Implemented | Steady Queue workers do not auto-reload on file changes; documentation reflects this. | Same constraint Huey had. |
| req-tap-cares-task-backend-deployment-4 | No Separate Service In v0 | Implemented | v0 does not introduce a separate compose service for Steady Queue. | Future deployments may. |

## Fork Safety
----
RID: `req-tap-cares-task-backend-fork-safety`
Status: `Implemented`

Steady Queue forks worker processes; Django ORM connections must be reset post-fork or they fence-post on TCP sockets. Steady Queue's worker model handles this internally per its docs, but the migration verification includes a smoke test that:

1. Brings up the stack with Steady Queue.
2. Triggers a manual collector run from the Administrivia UI.
3. Triggers another manual run while the first is in flight.
4. Verifies both `CollectionJob` rows transition cleanly through READY → RUNNING → SUCCESSFUL without `OperationalError`, `InterfaceError`, or "connection already closed" tracebacks.

If post-fork connection handling has any sharp edges, this is where they surface.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-fork-safety-1 | Post-Fork Smoke Test | Implemented (manual, CI-unguarded) | A manual two-collector smoke test passes without Django DB connection errors. | Documented in commit message of the implementing change. **This is a one-time manual check, not a regression guard**: no automated test runs `SteadyQueueBackend`, so a post-fork connection-handling regression would not be caught by CI — it would surface in dev/prod. Tracked for automation under [Backlog](#backlog) (`req-tap-cares-task-backend-backlog`). |
| req-tap-cares-task-backend-fork-safety-2 | Connection Errors Surfaced | Implemented | Any connection-handling regression surfaces as a test failure or visible Administrivia UI error, not silent data loss. | |

## Huey Removal
----
RID: `req-tap-cares-task-backend-huey-removal`
Status: `Implemented`

Huey is removed from the codebase as part of this refactor, in a separate commit after Steady Queue has been verified as the `TASKS` backend.

Removal surface:

- `huey` dependency in `pyproject.toml` (drop via `uv remove`).
- `huey.contrib.djhuey` from `INSTALLED_APPS` in `tap/settings.py`.
- `HUEY = {...}` config block in `tap/settings.py`.
- `tap_cares/huey_tasks.py` (the periodic `scheduler_tick` task — replaced by the Steady Queue `@recurring` declaration).
- The `tap_cares.huey_tasks` import in `tap_cares/apps.py::ready()`.
- The `manage.py run_huey` line in `docker/entrypoint.sh`.

The `spec-tap-cares-scheduler.md` requirements that referenced Huey explicitly (the Huey minute-tick requirement — since retitled `req-tap-cares-scheduler-tick` — and the `req-tap-cares-scheduler-dependencies` Huey clause) are updated to reflect Steady Queue. See [Migration Plan](#migration-plan).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-huey-removal-1 | Dependency Removed | Implemented | `huey` is no longer in `pyproject.toml` dependencies. | |
| req-tap-cares-task-backend-huey-removal-2 | Module Removed | Implemented | `tap_cares/huey_tasks.py` is deleted; `tap_cares/apps.py` no longer imports it. | |
| req-tap-cares-task-backend-huey-removal-3 | Settings Cleaned | Implemented | `INSTALLED_APPS` and the `HUEY` settings block no longer reference Huey. | |
| req-tap-cares-task-backend-huey-removal-4 | Entrypoint Cleaned | Implemented | `docker/entrypoint.sh` no longer starts `manage.py run_huey`. | |
| req-tap-cares-task-backend-huey-removal-5 | Scheduler Spec Updated | Implemented | `spec-tap-cares-scheduler.md` Huey requirements are rewritten in terms of Steady Queue and queue isolation. | |

## Migration Plan
----
RID: `req-tap-cares-task-backend-migration-plan`
Status: `Implemented`

The refactor lands in two commits with a verified-working state between them.

**Commit 1 — Add Steady Queue alongside Huey.**

- Add `steady_queue` dependency; declare `STEADY_QUEUE` settings with the two-worker (scheduler / default) split; add `steady_queue` to `INSTALLED_APPS`.
- Set `TASKS["default"]["BACKEND"]` to `SteadyQueueBackend` for dev/prod settings; preserve `ImmediateBackend` for the test settings path.
- Run migrations to create Steady Queue's tables.
- Add a second background process to `docker/entrypoint.sh` for `manage.py steady_queue` (Huey is still running in parallel).
- Smoke-test: trigger a manual collector run from Administrivia, verify `CollectionJob` lifecycle transitions through READY → RUNNING → SUCCESSFUL with real wall-clock gaps.
- Smoke-test: Huey's periodic tick still fires (no behavior change yet).
- Run the test suite; verify it still passes via `ImmediateBackend`.

If anything regresses, roll back to the prior `ImmediateBackend` configuration — `run_collector` is unchanged so the collector code path is identical regardless of backend.

**Commit 2 — Replace Huey with Steady Queue `@recurring`.**

- Author `tap_cares/task_backend.py` (or similar) with the `@recurring` `scheduler_tick` declaration on the `scheduler` queue.
- Remove Huey from settings, deps, entrypoint, and `tap_cares/apps.py`.
- Delete `tap_cares/huey_tasks.py`.
- Update `spec-tap-cares-scheduler.md`: replace `req-tap-cares-scheduler-huey-*` ACIDs with Steady-Queue-flavored equivalents; reword `req-tap-cares-scheduler-dependencies` to drop Huey and add a cross-reference to this spec.
- Smoke-test: confirm the recurring tick fires at the next minute boundary; confirm a fresh schedule produces a `ScheduleFire` and a `CollectionJob` runs to completion.

After Commit 2: one task backend, two isolated workers, the on-grid scheduler unchanged, the test suite unchanged.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-migration-plan-1 | Two-Commit Rollout | Implemented | The refactor lands in two commits — backend swap, then Huey removal — with a verifiably working state between them. | |
| req-tap-cares-task-backend-migration-plan-2 | Rollback Available | Implemented | Reverting Commit 1 alone returns to the prior `ImmediateBackend` configuration without code changes elsewhere. | |
| req-tap-cares-task-backend-migration-plan-3 | Spec Sync At Commit 2 | Implemented | `spec-tap-cares-scheduler.md` is updated in the same commit that removes Huey, so scheduler spec and code never disagree. | |
| req-tap-cares-task-backend-migration-plan-4 | Test Suite Continuity | Implemented | The full `pytest tap_cares/tests/` suite passes both at the boundary between Commit 1 and Commit 2 and after Commit 2. | |

## Backlog
----
RID: `req-tap-cares-task-backend-backlog`
Status: `Backlog`

Deferred:

- **Separate compose service for Steady Queue.** v0 runs it in-container; production may want process isolation.
- **Multi-machine workers.** Steady Queue supports horizontal scaling out of the box; v0 runs one supervisor on one host.
- **Alternative backends.** Redis, RabbitMQ, or other DEP 0014 backends if scale ever demands them.
- **Concurrency controls via `@limits_concurrency`.** Steady Queue's per-task concurrency primitives are not used in v0; TAP's per-schedule `max_active_runs` is the only concurrency surface. If TAP-level concurrency proves insufficient, Steady Queue's controls become a natural extension.
- **Task observability surface.** Steady Queue ships a Django admin UI for inspecting / retrying / discarding tasks. Whether TAP exposes that, hides it behind administrivia, or relies on it as-is is a separate design decision.
- **Stuck `PENDING` fire sweeper.** A scheduler fire stuck in `PENDING` indicates the scheduler tick crashed mid-stage-2 (see `req-tap-cares-scheduler-fire-model`). Detection and resolution are independent of the task-backend choice.
- **`run_after` scheduling.** Steady Queue supports delayed tasks via `run_after`. v0 doesn't use it.
- **Collector hot-reload (supervisor self-re-exec on a code-generation marker).** The flip side of `req-tap-cares-task-backend-deployment-3`'s No-Auto-Reload constraint: the supervisor is long-lived and forks every worker from its boot-time memory image, so a collector (or any task code) registered *after* the supervisor booted is invisible to all workers until the supervisor process is replaced. v0's answer is "restart the container." A future dev-loop ergonomic: a sentinel (git SHA, file mtime, `SIGHUP`, or a deploy-table row) that, when it changes, makes the supervisor drain its forks via the existing `terminate_gracefully()` and `os.execv()` itself into a fresh `manage.py steady_queue` — a clean fresh interpreter against current code, same PID, no module-reload fragility (the gunicorn/`runserver` autoreload pattern). This is a **process-lifecycle** seam only: it reuses trusted-startup `AppConfig.ready()` registration verbatim and must **not** become a dynamic code-loading path (`req-tap-cares-collector-registry-6` in `spec-tap-cares-collector.md` forbids importing runners from grid data — that invariant survives this seam untouched). Distinct from, and pairs with, the **resilient runner resolution** seam (`req-tap-cares-collector-registry`, `spec-tap-cares-collector.md`): hot-reload makes a new registration *current*; resilient resolution makes its *absence* fail honestly and early until it is. Pure dev-inner-loop friction (prod redeploys restart processes for free); build only on a demand signal.
- **Automated async-integration coverage.** No automated test runs `SteadyQueueBackend`; the entire delivery seam between `run_collection` and a real worker is CI-unguarded. Specifically untested by CI: post-fork DB-connection reset (`req-...-fork-safety`), scheduler/default queue process isolation (`req-...-queue-isolation`), wall-clock READY→RUNNING→SUCCESSFUL transitions, queue-pickup latency, and stuck-`RUNNING` after a worker crash. The `on_commit` deferral *is* now positively guarded by `TestTransactionalIntegrity` (`req-...-transactional-integrity-1`), and collector/scheduler *logic* is covered under `ImmediateBackend`; the gap is the real-worker integration layer. The honest cost tiering: (1) the deferral guard — **done**; (2) a marked, opt-in integration suite booting a real `SteadyQueueBackend` + worker and polling for terminal state — backlog (slow, fork/timing-sensitive, needs harness plumbing); (3) fork-safety as a CI smoke *job* (boot stack, two concurrent runs, assert clean lifecycle + no `OperationalError`/`InterfaceError`) rather than a unit test — backlog. Until (2)/(3) land, `req-...-fork-safety-1` is "manual, CI-unguarded" by design, not by oversight.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-task-backend-backlog-1 | Deferred Work Named | Backlog | Non-v0 task-backend capabilities are tracked here rather than being partially specified. | |
| req-tap-cares-task-backend-backlog-2 | Async-Integration Coverage Gap Named | Backlog | The CI-unguarded real-worker integration seam (fork safety, queue isolation, wall-clock lifecycle, pickup latency) is named here with a cost tiering, rather than left as implied confidence behind green unit tests. The `on_commit` deferral guard (tier 1) is implemented; tiers 2–3 are deferred. | Counters the "false confidence" failure mode (`docs/aar/2026-05-16-aws-collector-sprint-sprawl.md` §4): a requirement whose only guard is a one-time manual smoke or "the suite still passes" is effectively unguarded and must be labeled as such. |
| req-tap-cares-task-backend-backlog-3 | Collector Hot-Reload Seam Named | Backlog | The supervisor-self-re-exec-on-generation-marker reload seam is named here as the deliberate complement to `req-tap-cares-task-backend-deployment-3` (No Auto-Reload), constrained to process-lifecycle only (no grid-data code loading; `req-tap-cares-collector-registry-6` survives untouched) and explicitly paired with the resilient-runner-resolution seam. Build only on a dev-loop demand signal. | Discovered 2026-05-19: a 28h-stale supervisor surfaced a registered collector as a confusing mid-job `RUNNER_UNAVAILABLE`. The loud self-diagnosing failure message (`tap_cares/services.py`) is the shipped interim; this seam + the resolution seam are the deferred structural follow-ups. |
