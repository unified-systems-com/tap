# tap-cares Scheduler Specification

## Philosophy

The tap-cares scheduler is TAP's on-grid recurring trigger system.

The scheduler decides when a collector should run. It does not own collector execution. Once a schedule determines that a collector should run, it calls `run_collection(...)` and lets the collector runtime create the `CollectionJob`, create the `HAS_COLLECTION_JOB` edge, enqueue the task, and manage the job lifecycle.

Steady Queue's recurring-task scheduler is the v0 clock that wakes once per minute and dispatches a tick task on the dedicated `scheduler` queue. The tick task calls `tap_cares.scheduler.evaluate_tick()`. TAP schedule nodes remain the source of truth — Steady Queue is replaceable infrastructure under the on-grid scheduling model. See `spec-tap-cares-task-backend.md` for the task backend choice; this spec covers the TAP-level scheduler service that runs on top of it.

The v0 scheduler should be deliberately small: UTC cron expressions, collector targets only, no catch-up execution, durable fire records, and one simple overlap guard.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | On-Grid      | Represent schedules and schedule fires as TAP-managed graph objects |
| 2. | Collector-Only | Support recurring collector execution as the first scheduler target |
| 3. | Observable   | Record each evaluated matching cron slot — including triggered, skipped, and failed fires — plus detected gaps |
| 4. | Minimal      | Use cron semantics, UTC, minute resolution, and a small field set |
| 5. | Bounded      | Prevent a schedule from piling up overlapping collector runs |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-scheduler-scope | [Scheduler Scope](#scheduler-scope) | Implemented | Defines v0 as collector-only recurring execution |
| req-tap-cares-scheduler-tick | [Minute Tick](#minute-tick) | Implemented | A Steady Queue `@recurring` task evaluates enabled schedules once per minute on a dedicated queue |
| req-tap-cares-scheduler-dependencies | [Implementation Dependencies](#implementation-dependencies) | Implemented | croniter (cron parsing); Steady Queue task backend per `spec-tap-cares-task-backend.md` |
| req-tap-cares-scheduler-model | [Schedule Model](#schedule-model) | Implemented | User-creatable on-grid schedule node |
| req-tap-cares-scheduler-fire-model | [ScheduleFire Model](#schedulefire-model) | Implemented | Internal-only durable record for each evaluated due slot |
| req-tap-cares-scheduler-edges | [Scheduler Edges](#scheduler-edges) | Implemented | Graph relationships between schedules, fires, collectors, and jobs |
| req-tap-cares-scheduler-cron | [Cron Semantics](#cron-semantics) | Implemented | UTC, minute-resolution cron parsed with croniter, no catch-up execution |
| req-tap-cares-scheduler-missed-count | [Missed Count](#missed-count) | Implemented | Detect schedule gaps without backfilling work |
| req-tap-cares-scheduler-dedupe | [Slot Dedupe](#slot-dedupe) | Implemented | Atomic optimistic-update claim prevents duplicate fires |
| req-tap-cares-scheduler-concurrency | [Schedule Concurrency](#schedule-concurrency) | Implemented | Per-schedule max active runs |
| req-tap-cares-scheduler-trigger-provenance | [Trigger Provenance Handoff](#trigger-provenance-handoff) | Implemented | Scheduler hands off trigger metadata to the collector subsystem |
| req-tap-cares-scheduler-backlog | [Backlog](#backlog) | Backlog | Deferred scheduler capabilities |

## Scheduler Scope
----
RID: `req-tap-cares-scheduler-scope`
Status: `Implemented`

v0 schedules target collectors only.

A schedule represents a recurring policy that says "run this collector when this cron expression matches." Emitters, receivers, actions, ad hoc run-now requests, and generic capability targets are future work. The model should not paint TAP into a corner, but the v0 implementation and acceptance criteria are collector-specific.

The scheduler is a trigger system. It must not:

- import collector implementation modules directly
- enqueue `run_collector` directly
- create `CollectionJob` rows directly
- create `HAS_COLLECTION_JOB` edges directly
- mutate collector output or GRIFT batches

When a schedule fires successfully, it invokes `tap_cares.services.run_collection(...)` for the target `Collector`.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-scope-1 | Collector-Only v0 | Implemented | v0 schedules can target `Collector` nodes and no other CARES capability type. | |
| req-tap-cares-scheduler-scope-2 | Uses run_collection | Implemented | Successful scheduled execution invokes `run_collection(...)`; the scheduler does not reach behind that boundary. | See `spec-tap-cares-collector.md` `req-tap-cares-collector-run-collection`. |
| req-tap-cares-scheduler-scope-3 | No Direct Task Enqueue | Implemented | The scheduler never calls `run_collector.enqueue(...)` directly. | |

## Minute Tick
----
RID: `req-tap-cares-scheduler-tick`
Status: `Implemented`

A Steady Queue `@recurring` task wakes once per minute and evaluates schedules.

The tick task (`tap_cares.task_backend.scheduler_tick`) is declared with `@recurring(schedule="* * * * *", key="tap_cares_scheduler_tick", queue_name="scheduler")` and:

1. Computes the current UTC minute slot by truncating wall-clock time to minute precision.
2. Finds enabled `Schedule` nodes.
3. Evaluates each schedule's cron expression against the current slot.
4. For matching schedules, claims the slot, creates a `ScheduleFire`, applies the overlap guard, and calls `run_collection(...)` when allowed.

Steady Queue is not the schedule database. Schedule state, schedule targets, fire history, missed counts, and links to collection jobs all live on the TAP grid — Steady Queue's `steady_queue_recurringexecution` table holds exactly one row (the tick task itself).

The tick task is dispatched to the dedicated `scheduler` queue, served by a single forked worker process. A backlog of collector tasks on the `default` queue cannot starve the clock — see `spec-tap-cares-task-backend.md` `req-tap-cares-task-backend-queue-isolation` for the worker topology.

v0 deploys a single scheduler-queue worker. Multi-worker deployments are out of scope. The slot dedupe in `req-tap-cares-scheduler-dedupe` is correct under multiple workers because of the optimistic atomic claim, but multi-worker support is not exercised, not benchmarked, and not part of the v0 acceptance surface. This is an intentional, explicit choice — not a presumption — so that future work to support multiple workers or a hot/standby pair can change it deliberately.

A separate host-level watcher that detects Steady Queue supervisor death and multiple-supervisor conditions is tracked in the backlog.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-tick-1 | Minute Tick | Implemented | Steady Queue's recurring-task scheduler dispatches the tick once per minute. | No per-second evaluation in v0. |
| req-tap-cares-scheduler-tick-2 | UTC Slot | Implemented | The scheduler evaluates an exact UTC minute slot, not arbitrary sub-minute wall-clock time. | |
| req-tap-cares-scheduler-tick-3 | TAP Owns State | Implemented | Steady Queue is only the clock/worker; durable scheduler state is stored in TAP graph objects. | |
| req-tap-cares-scheduler-tick-4 | Single Worker v0 | Implemented | v0 runs exactly one Steady Queue scheduler-queue worker process; multi-worker deployment is out of scope. | Slot dedupe is correct under multi-worker but multi-worker is not v0-supported. |
| req-tap-cares-scheduler-tick-5 | Dedicated Queue | Implemented | The tick task is tagged with `queue_name="scheduler"` and served by a worker that polls only the scheduler queue, so collector workload cannot starve the clock. | Cross-ref `spec-tap-cares-task-backend.md` `req-tap-cares-task-backend-queue-isolation`. |

## Implementation Dependencies
----
RID: `req-tap-cares-scheduler-dependencies`
Status: `Implemented`

The scheduler implementation requires:

- **croniter** — cron-expression parsing, validation, and slot iteration (used by the missed-count walk and tick-time match check), added through uv.
- **Steady Queue** — the task backend that hosts both the once-per-minute tick task and the collector execution. Its dependency and deployment are governed by `spec-tap-cares-task-backend.md` `req-tap-cares-task-backend-steady-queue`; the scheduler spec does not re-declare them.

This requirement is about scheduler-specific dependency management only. It does not change the runtime rule that Steady Queue is the clock/worker and TAP graph objects are the durable schedule source of truth.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-dependencies-1 | croniter Dependency | Implemented | Cron parsing, validation, and slot iteration use the `croniter` library, added through uv. | One parser binds write-time validation to tick-time evaluation so they cannot disagree. |
| req-tap-cares-scheduler-dependencies-2 | Task Backend Cross-Ref | Implemented | The task backend (Steady Queue) is spec'd in `spec-tap-cares-task-backend.md`; the scheduler depends on whatever DEP 0014 backend that spec selects. | Replaceable infra; scheduler spec does not own the choice. |
| req-tap-cares-scheduler-dependencies-3 | Workspace-Compatible | Implemented | If the uv workspace/plugin-dependency pattern lands first, scheduler dependency installation follows that pattern. | Cross-reference `tap_plugins/specs/spec-tap-plugin-architecture.md` `req-tap-plugin-arch-python-deps`. |
| req-tap-cares-scheduler-dependencies-4 | State Boundary Unchanged | Implemented | Adding a task backend dependency does not make the backend the durable schedule store. | |

## Schedule Model
----
RID: `req-tap-cares-scheduler-model`
Status: `Implemented`

`Schedule` is the on-grid policy node for recurring collector execution.

`Schedule` is implemented as a standard TAP-managed `BaseModel` node and is **user-creatable** — it is **not** `INTERNAL_ONLY`. Users may create and modify schedules through the standard public CRUD API, and GRIFT may seed schedules from plugins. All writes still route through a dedicated tap-cares scheduler service so that cron validation, default dimensions, and seed/non-seed parity stay consistent.

When implementing `Schedule` (and `ScheduleFire`, and the scheduler edges), use the [`add-model`](../../.claude/skills/add-model/SKILL.md) and [`add-edge`](../../.claude/skills/add-edge/SKILL.md) skills. The skills enforce the BaseModel contract, dual schema, validation hooks, manifest registration, and the related-edge declarations the scheduler relies on.

Every `Schedule` has a human-readable `name` and plain-text `description`.

Minimal v0 fields:

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Required human-readable name |
| `description` | string | Plain-text explanation of what this schedule does |
| `enabled` | bool | Disabled schedules are ignored and do not accumulate missed runs |
| `enabled_at` | datetime/null | Wall-clock time when `enabled` most recently transitioned `false → true`; bounds the missed-count walk so long disabled stretches do not produce huge missed counts |
| `cron_expression` | string | Five-field cron expression interpreted in UTC at minute resolution; validated via `croniter` at write time |
| `last_schedule_fired` | datetime/null | Last UTC cron slot the scheduler processed for this schedule (renamed from the earlier draft's `last_scheduled_for` to align with the `HAS_FIRED`/`ScheduleFire` vocabulary) |
| `max_active_runs` | positive integer | Maximum active runs allowed for this schedule; default `1` |

`last_schedule_fired` is a processed-slot cursor, not a prediction. It exists to make the per-minute scheduler idempotent and to detect gaps. The scheduler advances it to the current slot when it processes that slot, whether the resulting fire is triggered, skipped, or failed.

`enabled_at` is updated by the scheduler service whenever `enabled` flips from `false` to `true`. The missed-count walk uses it as a lower bound (see `req-tap-cares-scheduler-missed-count`) so disabled stretches do not show up as missed runs after the schedule is re-enabled.

`max_active_runs` is per schedule in v0. It is not a collector-wide concurrency limit.

`Schedule` deletion follows the service-layer delete default (tombstone). Cascading delete of related `ScheduleFire` nodes and `HAS_FIRED`/`SCHEDULED_TARGET` edges is not yet defined; revisit when the project's wider cascading-delete behavior is sorted (tracked in the backlog).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-model-1 | Standard BaseModel | Implemented | `Schedule` is a TAP-managed `BaseModel` node with a backing `Entity`. | Implemented via the `add-model` skill. |
| req-tap-cares-scheduler-model-2 | Name And Description | Implemented | `Schedule` has required `name` and `description` fields. | |
| req-tap-cares-scheduler-model-3 | Minimal Fields | Implemented | v0 `Schedule` exposes only `name`, `description`, `enabled`, `enabled_at`, `cron_expression`, `last_schedule_fired`, and `max_active_runs`. | |
| req-tap-cares-scheduler-model-4 | Processed-Slot Cursor | Implemented | `last_schedule_fired` records the most recent processed cron slot, not the most recent task completion time. | |
| req-tap-cares-scheduler-model-5 | Default Overlap Guard | Implemented | `max_active_runs` defaults to `1` and must be greater than or equal to `1`. | |
| req-tap-cares-scheduler-model-6 | User Creatable | Implemented | `Schedule` is not `INTERNAL_ONLY`; users may create and modify schedules through the standard public CRUD API and via GRIFT seed data. | Writes still route through the scheduler service for cron validation and default dimensions. |
| req-tap-cares-scheduler-model-7 | Cron Validation At Write | Implemented | `cron_expression` is validated using `croniter` at write time; invalid expressions are rejected before save. | Enforced via `FIELD_VALIDATION_SCHEMA` and the scheduler service. |
| req-tap-cares-scheduler-model-8 | Enabled-At Tracked | Implemented | `enabled_at` is set when `enabled` transitions `false → true` and is used as the lower bound for the missed-count walk. | |

## ScheduleFire Model
----
RID: `req-tap-cares-scheduler-fire-model`
Status: `Implemented`

`ScheduleFire` is the on-grid execution-decision record for one evaluated due slot of a schedule. It is **`INTERNAL_ONLY`** — only the scheduler subsystem may create or modify fire nodes.

A `ScheduleFire` is not the collector run. The collector run is still represented by `CollectionJob`. `ScheduleFire` records the scheduler's decision for a due slot and links to a `CollectionJob` only when the schedule actually triggers collection.

A `ScheduleFire` is created **only when an enabled schedule's cron expression matches the current minute slot**. Ticks where no schedules match the current minute do not produce `ScheduleFire` rows. This keeps the fire history tightly correlated with per-schedule decisions rather than recording every scheduler-tick wake-up.

Every `ScheduleFire` has a human-readable `name` and plain-text `description`.

Minimal v0 fields:

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Human-readable fire name, usually derived from schedule name and slot |
| `description` | string | Plain-text explanation of the scheduled decision |
| `status` | enum | `pending` (initial, transient), `triggered`, `skipped`, or `failed` |
| `scheduled_for` | datetime | UTC cron slot being evaluated |
| `fired_at` | datetime | Wall-clock time when the scheduler evaluated the slot (always set, non-null) |
| `missed_count` | integer | Number of matching cron slots skipped before this slot; default `0` |
| `summary` | string | One-line human-readable description of the scheduler decision — covers triggered, skipped, and failed cases in a single field |

`ScheduleFire.status` describes scheduler behavior only:

- `pending` — Stage 1 of the tick has committed (slot claimed, fire row created) but Stage 2 has not yet decided the outcome. Transient; should never be observed externally for more than one tick. A fire stuck in `pending` indicates the scheduler crashed between Stage 1 commit and Stage 2 completion.
- `triggered` — the scheduler called `run_collection(...)` successfully and a `TRIGGERED_JOB` edge links to the resulting `CollectionJob`.
- `skipped` — the slot was due but no collector run was started, for example because `max_active_runs` was already reached.
- `failed` — the scheduler failed while processing the slot, including when `run_collection(...)` itself raised before producing a `CollectionJob`. No `TRIGGERED_JOB` edge is created for failed fires.

`pending` is the initial value at fire creation in Stage 1; Stage 2 transitions the fire to one of the three terminal statuses. Collector success or failure is recorded on `CollectionJob.status`, not copied back into `ScheduleFire.status`.

`summary` is freeform but the scheduler writes short, consistent strings the administrivia UI can render directly. Suggested vocabulary:

- triggered → `"Triggered run for <schedule name>."`
- skipped → `"Skipped: max_active_runs reached (N active)."`
- failed → `"Scheduler error: <short reason from the exception>."`

The exact text is implementation-flexible; the requirement is that `summary` is always populated and that the scheduler's failure path writes a meaningful summary rather than leaving it empty.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-fire-model-1 | Standard BaseModel | Implemented | `ScheduleFire` is a TAP-managed `BaseModel` node with a backing `Entity`. | Implemented via the `add-model` skill. |
| req-tap-cares-scheduler-fire-model-2 | Internal Only | Implemented | `ScheduleFire` is `INTERNAL_ONLY`; only the scheduler subsystem creates or modifies fire nodes. | |
| req-tap-cares-scheduler-fire-model-3 | Name And Description | Implemented | `ScheduleFire` has required `name` and `description` fields. | |
| req-tap-cares-scheduler-fire-model-4 | Decision Record | Implemented | Each `ScheduleFire` records the scheduler decision for one due cron slot. | |
| req-tap-cares-scheduler-fire-model-5 | Scheduler Status Only | Implemented | `ScheduleFire.status` records scheduler decision state, not the terminal collector job state. The transient `pending` value at creation transitions to `triggered`, `skipped`, or `failed` in Stage 2. | |
| req-tap-cares-scheduler-fire-model-6 | Missed Count Field | Implemented | `ScheduleFire` has an integer `missed_count` defaulting to `0`. | |
| req-tap-cares-scheduler-fire-model-7 | Summary Field | Implemented | `ScheduleFire.summary` is a single freeform one-liner that covers triggered, skipped, and failed cases; the scheduler always sets it. | Replaces the earlier draft's separate `skip_reason` and `error_summary` fields. |
| req-tap-cares-scheduler-fire-model-8 | Created Only On Match | Implemented | A `ScheduleFire` is created only when an enabled schedule's cron expression matches the current minute slot. | Non-matching scheduler ticks produce no rows. |
| req-tap-cares-scheduler-fire-model-9 | run_collection Failure | Implemented | If `run_collection(...)` raises during a triggered slot, the fire is recorded with `status = failed`, no `TRIGGERED_JOB` edge, and a `summary` describing the failure. | The transactional unit must close in this state — no half-triggered fires. |
| req-tap-cares-scheduler-fire-model-10 | fired_at Non-Null | Implemented | `fired_at` is always set at fire creation; it is non-null. | |

## Scheduler Edges
----
RID: `req-tap-cares-scheduler-edges`
Status: `Implemented`

The v0 scheduler graph uses these edges:

```text
Schedule --SCHEDULED_TARGET--> Collector
Schedule --HAS_FIRED--> ScheduleFire
ScheduleFire --TRIGGERED_JOB--> CollectionJob
```

`SCHEDULED_TARGET` ties the schedule policy to the collector capability it can run. v0 requires **exactly one** `SCHEDULED_TARGET` edge per `Schedule`. Future support for multiple targets ordered by a property on `SCHEDULED_TARGET` (e.g. an `ordering` integer for sequential runs at the same slot) is tracked in the backlog.

`HAS_FIRED` (past tense — every such edge points at a fire that already happened) ties a durable fire/decision record to the schedule that produced it.

`TRIGGERED_JOB` exists only for fires whose status is `triggered`. Skipped or failed fires do not have a `TRIGGERED_JOB` edge because no collection job was started.

All three edges are **naked** in v0 — no `property_schema` is declared on the edge types. When a property is needed later (for example an `ordering` integer on `SCHEDULED_TARGET`), it will be added by the relevant requirement change.

The existing collector edge remains unchanged:

```text
Collector --HAS_COLLECTION_JOB--> CollectionJob
```

This means a scheduled collection job is reachable in two useful ways:

```text
Schedule --HAS_FIRED--> ScheduleFire --TRIGGERED_JOB--> CollectionJob
Collector --HAS_COLLECTION_JOB--> CollectionJob
```

**Internal-state edges and `INTERNAL_ONLY` enforcement.** `HAS_FIRED` and `TRIGGERED_JOB` materially carry scheduler state — they are the bridge between a scheduler decision (`ScheduleFire`) and a collector run (`CollectionJob`). Today `INTERNAL_ONLY` is enforced on node creation but does not necessarily prevent user code from creating edges that point to internal-only nodes. Allowing user code to write a `HAS_FIRED` or `TRIGGERED_JOB` would let it inject phantom decisions or repoint trigger lineage. Extending `INTERNAL_ONLY` enforcement to scheduler-owned edges is tracked in the backlog and should be revisited before public API surfaces grow.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-edges-1 | SCHEDULED_TARGET Edge | Implemented | tap-cares declares `SCHEDULED_TARGET` from `Schedule` to `Collector` for v0. | Implemented via the `add-edge` skill. |
| req-tap-cares-scheduler-edges-2 | One Target Per Schedule | Implemented | v0 requires exactly one `SCHEDULED_TARGET` edge per Schedule. | Multiple targets with ordering are backlog. |
| req-tap-cares-scheduler-edges-3 | HAS_FIRED Edge | Implemented | tap-cares declares `HAS_FIRED` from `Schedule` to `ScheduleFire`. | |
| req-tap-cares-scheduler-edges-4 | TRIGGERED_JOB Edge | Implemented | tap-cares declares `TRIGGERED_JOB` from `ScheduleFire` to `CollectionJob`. | Only present for triggered fires. |
| req-tap-cares-scheduler-edges-5 | HAS_COLLECTION_JOB Preserved | Implemented | Scheduled collection still creates the existing `Collector --HAS_COLLECTION_JOB--> CollectionJob` edge through `run_collection(...)`. | |
| req-tap-cares-scheduler-edges-6 | Edges Naked | Implemented | `SCHEDULED_TARGET`, `HAS_FIRED`, and `TRIGGERED_JOB` declare no `property_schema` in v0. | |

## Cron Semantics
----
RID: `req-tap-cares-scheduler-cron`
Status: `Implemented`

v0 schedules use five-field cron expressions:

```text
minute hour day-of-month month day-of-week
```

Cron expressions are interpreted in UTC and parsed/iterated via `croniter`. The scheduler evaluates only minute-level slots. Sub-minute precision, named time zones, daylight-saving-time policy, seconds fields, calendars, and interval-specific fields are out of scope for v0.

There is no catch-up execution in v0. If Steady Queue, the app, or the host is down when a schedule would have matched, TAP does not enqueue historical collector runs for those missed slots.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-cron-1 | Five-Field Cron | Implemented | `cron_expression` stores a five-field cron expression. | |
| req-tap-cares-scheduler-cron-2 | UTC Only | Implemented | Cron matching is interpreted in UTC in v0. | |
| req-tap-cares-scheduler-cron-3 | Minute Resolution | Implemented | The scheduler evaluates minute slots only; seconds are ignored. | |
| req-tap-cares-scheduler-cron-4 | No Catch-Up Execution | Implemented | Missed slots are not backfilled or executed later in v0. | |
| req-tap-cares-scheduler-cron-5 | croniter | Implemented | Cron parsing, validation, and slot iteration use the `croniter` library. | One parser binds write-time validation to tick-time evaluation. |

## Missed Count
----
RID: `req-tap-cares-scheduler-missed-count`
Status: `Implemented`

The scheduler detects gaps by comparing a lower bound on the schedule's history to the current matching slot.

When the current UTC minute matches a schedule's cron expression, the scheduler walks matching slots between a lower bound and the current slot:

1. Compute the lower bound: `max(last_schedule_fired, enabled_at)`. If both are null, the lower bound is null (a brand-new schedule's first fire).
2. If the lower bound is null, `missed_count = 0`.
3. Otherwise, use `croniter` to count cron slots strictly between the lower bound and the current slot.
4. Store that count on the current slot's `ScheduleFire.missed_count`.
5. Continue processing only the current slot.

Example for an every-minute schedule:

```text
last_schedule_fired = 12:00
enabled_at          = 11:50
current slot        = 12:05
lower bound         = max(12:00, 11:50) = 12:00
missed slots        = 12:01, 12:02, 12:03, 12:04
missed_count        = 4
```

Example after a long disabled stretch:

```text
last_schedule_fired = 10:00
enabled_at          = 12:03   # schedule was disabled from 10:01 to 12:03
current slot        = 12:05
lower bound         = max(10:00, 12:03) = 12:03
missed slots        = 12:04
missed_count        = 1
```

The fire for the current slot proceeds normally after this accounting. It may trigger a collection job, or it may be skipped because `max_active_runs` has been reached.

Disabled schedules do not accumulate missed runs. The combination of `enabled_at` as a lower bound and "not evaluated while disabled" gives `missed_count` a coherent meaning across disable/enable cycles.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-missed-count-1 | Lower-Bound Walk | Implemented | Missed slots are detected by walking from `max(last_schedule_fired, enabled_at)` to the current matching cron slot. | |
| req-tap-cares-scheduler-missed-count-2 | Count Only | Implemented | Missed slots increment `missed_count`; they do not create backfilled collection jobs. | |
| req-tap-cares-scheduler-missed-count-3 | Current Fire Carries Count | Implemented | The current slot's `ScheduleFire` stores the missed count summary. | |
| req-tap-cares-scheduler-missed-count-4 | Disabled Ignored | Implemented | Disabled schedules do not accumulate or later report missed counts for disabled periods. | `enabled_at` is the lower bound so disabled stretches are excluded. |
| req-tap-cares-scheduler-missed-count-5 | croniter Iteration | Implemented | Matching-slot iteration uses `croniter` rather than ad hoc minute math. | |

## Slot Dedupe
----
RID: `req-tap-cares-scheduler-dedupe`
Status: `Implemented`

The scheduler must process a schedule/slot pair at most once.

### Implementation

The scheduler claims a slot with an **optimistic conditional UPDATE** wrapped in a `transaction.atomic()` block, then creates the `ScheduleFire` inside the same transaction. `run_collection(...)` is invoked **after** the claim transaction commits so collector dispatch does not hold the schedule row lock or rely on the claim being durable inside its own transaction.

```python
# Stage 1 — atomic claim + provisional fire
with transaction.atomic():
    claimed = (
        Schedule.objects.filter(pk=schedule.pk)
        .filter(
            Q(last_schedule_fired__lt=current_slot)
            | Q(last_schedule_fired__isnull=True)
        )
        .update(last_schedule_fired=current_slot)
    )
    if claimed == 0:
        return  # another worker already processed this slot
    fire = create_schedule_fire(schedule, current_slot, ...)
# Claim transaction commits here.

# Stage 2 — concurrency check + dispatch (outside the claim transaction)
if active_count(schedule) >= schedule.max_active_runs:
    update_schedule_fire(fire, status="skipped", summary=...)
    return

try:
    job = run_collection(schedule.target_collector, ...)
    update_schedule_fire(fire, status="triggered", summary=...)
    create_triggered_job_edge(fire, job)
except Exception as exc:
    update_schedule_fire(fire, status="failed", summary=...)
```

### Implications

- **Multi-worker safe.** Two workers racing on the same slot produce at most one `ScheduleFire`; the loser sees rowcount 0 and exits before creating a fire row. This is the property that lets v0's single-worker assumption (`req-tap-cares-scheduler-tick-4`) be relaxed later without redesigning dedupe.
- **Replay safe.** A retried tick task is also a duplicate slot for the schedule, and the same exclusion logic short-circuits it.
- **Dispatch outside the claim.** `run_collection(...)` runs after Stage 1 commits, so a synchronous task backend (e.g. ImmediateBackend in tests) does not execute the collector body before the fire row is durable. It also means the claim row lock is not held while the collector runs.
- **`ScheduleFire` has no denormalized `schedule` FK.** The canonical graph relationship is `Schedule --HAS_FIRED--> ScheduleFire`, matching the `Collector --HAS_COLLECTION_JOB--> CollectionJob` pattern. v0 enforces "one fire per slot" with the atomic claim plus `INTERNAL_ONLY` on `ScheduleFire`; no DB-level unique constraint is added. If a third defense layer is wanted later, a denormalized `schedule` column + `UniqueConstraint(schedule, scheduled_for)` is a backlog-eligible addition.
- **Status transitions are not atomic with the claim.** Fire status moves from its initial value (set at creation) to `triggered`, `skipped`, or `failed` in Stage 2. This is acceptable because the fire row exists from Stage 1 and observers see a row whose status converges shortly after.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-dedupe-1 | Duplicate Slot No-Op | Implemented | If `last_schedule_fired == current_slot`, the scheduler does not create a `ScheduleFire`. | |
| req-tap-cares-scheduler-dedupe-2 | Atomic Claim | Implemented | Claiming `last_schedule_fired` (optimistic conditional UPDATE) and creating the `ScheduleFire` happen inside one `transaction.atomic()` block. | |
| req-tap-cares-scheduler-dedupe-3 | One Fire Per Slot | Implemented | A schedule cannot produce more than one `ScheduleFire` for the same `scheduled_for` slot. | Enforced by the atomic claim plus `INTERNAL_ONLY` on `ScheduleFire`. A DB-level unique constraint would require a denormalized `schedule` FK on `ScheduleFire`; deferred. |
| req-tap-cares-scheduler-dedupe-4 | Conditional UPDATE Mechanism | Implemented | The atomic claim uses an optimistic conditional UPDATE on `Schedule.last_schedule_fired` and bails when rowcount is 0. | Chosen over `SELECT ... FOR UPDATE` because it remains lock-light under future multi-worker deployments. |
| req-tap-cares-scheduler-dedupe-5 | Dispatch After Commit | Implemented | `run_collection(...)` is invoked only after the claim transaction commits. | Avoids holding the schedule row lock during collector execution and avoids synchronous-backend ordering hazards. |

## Schedule Concurrency
----
RID: `req-tap-cares-scheduler-concurrency`
Status: `Implemented`

Each schedule limits its own active scheduled runs with `max_active_runs`.

For v0, active runs are `CollectionJob` nodes linked from this schedule through:

```text
Schedule --HAS_FIRED--> ScheduleFire --TRIGGERED_JOB--> CollectionJob
```

where `CollectionJob.status` is `READY` or `RUNNING`. Both states are "in flight":

- `READY` means the job has been enqueued but a worker has not picked it up yet.
- `RUNNING` means a worker is actively executing the collector body.

Both count as active so the overlap guard does not pile additional fires on top of a queue that has not yet drained.

If the active count is greater than or equal to `Schedule.max_active_runs`, the scheduler creates a `ScheduleFire` for the current slot with:

```text
status  = skipped
summary = "Skipped: max_active_runs reached (N active)."
```

and does not call `run_collection(...)`.

This policy is intentionally similar to production systems that support "forbid overlap" behavior. v0 does not replace or cancel active runs.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-concurrency-1 | Per-Schedule Limit | Implemented | `max_active_runs` applies to runs triggered by the same schedule, not all runs of the target collector. | |
| req-tap-cares-scheduler-concurrency-2 | Active Statuses | Implemented | `READY` and `RUNNING` collection jobs both count as active for scheduler overlap checks. | Counts enqueued-but-not-started together with currently-executing as in-flight. |
| req-tap-cares-scheduler-concurrency-3 | Skipped Fire | Implemented | A due slot blocked by the active-run limit creates a skipped `ScheduleFire` with a `summary` explaining the reason. | |
| req-tap-cares-scheduler-concurrency-4 | No Replace In v0 | Implemented | v0 does not cancel, replace, or interrupt already-active collection jobs. | |

## Trigger Provenance Handoff
----
RID: `req-tap-cares-scheduler-trigger-provenance`
Status: `Implemented`

Scheduled collector execution must preserve why the collector ran, but the **durable provenance fields live on `CollectionJob`**, not on the scheduler. The scheduler is one trigger source among several (scheduler today, manual UI button, future API) and hands the relevant trigger metadata to `run_collection(...)`; the collector subsystem owns persistence.

The provenance model on `CollectionJob` is a small pair of fields:

- `manual_run` (bool, default `false`) — `true` only when a human explicitly pushed the run-now button or used another manual-run path.
- `manual_run_source` (string, optional) — short identifier of the manual surface (e.g. `"administrivia.run_button"`, `"shell"`). Empty when `manual_run` is `false`.

Scheduled runs do **not** set `manual_run`. Their provenance is the inbound `TRIGGERED_JOB` edge from the `ScheduleFire`, which is the canonical scheduler-trigger record. A future API trigger source would extend the same pattern (likely an `api_run` flag or an analogous edge).

The full schema, validation, and migration story for `manual_run` / `manual_run_source` therefore lives in the **collector** specification — see `spec-tap-cares-collector.md` (`req-tap-cares-collector-run-collection-9` and `req-tap-cares-collector-job-model-21`, its Manual Run Provenance criteria). The scheduler spec only asserts the handoff contract.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-trigger-provenance-1 | Scheduler Doesn't Set Manual | Implemented | Scheduler invocations of `run_collection(...)` do not set `manual_run`; the resulting `CollectionJob.manual_run` is `false`. | |
| req-tap-cares-scheduler-trigger-provenance-2 | Scheduler Trigger Via Edge | Implemented | The scheduler-trigger relationship is captured by `ScheduleFire --TRIGGERED_JOB--> CollectionJob`, not by a field on the job. | The edge is the canonical record. |
| req-tap-cares-scheduler-trigger-provenance-3 | Collector Spec Owns Fields | Implemented | Persistence and schema for `manual_run` / `manual_run_source` belong in `spec-tap-cares-collector.md`; this requirement is the handoff contract only. | Cross-reference the collector spec's manual-run-provenance requirement. |
| req-tap-cares-scheduler-trigger-provenance-4 | Caller Context Separate | Implemented | `caller_context` remains the authority/user context; manual-run metadata describes the mechanism, not the actor. | |

## Backlog
----
RID: `req-tap-cares-scheduler-backlog`
Status: `Backlog`

The following are intentionally deferred:

- schedule targets beyond collectors
- **multiple `SCHEDULED_TARGET` edges per `Schedule`**, ordered via a property on the edge (e.g. an `ordering` integer) for running several collectors at the same slot
- run-now trigger nodes that mediate manual execution
- catch-up or backfill execution for missed slots
- time zone support beyond UTC
- second-level cron support
- stale active run timeout, stuck-job sweep, or administrator resolution flow
- replace-running or cancel-running overlap policy
- collector-wide concurrency limits
- schedule parameter payloads and per-run input overrides
- schedule-fire retention and pruning
- richer scheduler tick health metrics
- **multi-worker Steady Queue scheduler-queue deployment** — relax `req-tap-cares-scheduler-tick-4` once we have a use case and benchmarks
- **Steady Queue supervisor watcher** — a separate host-level cron job (outside the Steady Queue supervisor) that detects whether the supervisor is alive and whether more than one instance is running. The watcher could restart it or raise an alert; deferred until the alerts system exists
- **`INTERNAL_ONLY` enforcement on edges** — extend the existing `INTERNAL_ONLY` protection so edges that point to internal-only nodes (e.g. `HAS_FIRED`, `TRIGGERED_JOB`) cannot be created by user code. Important because these edges materially carry scheduler decision lineage
- **Schedule cascade delete** — define how `ScheduleFire` rows and scheduler edges behave when a `Schedule` is deleted; revisit once the project's cascading-delete behavior is sorted

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-scheduler-backlog-1 | Deferred Work Named | Backlog | Non-v0 scheduler capabilities are explicitly tracked as backlog rather than being partially specified. | |
