"""tap_cares orchestration services.

`run_collection` is the public entry point for starting a collector run. It
creates the on-grid CollectionJob via `_create_node_internal` (CollectionJob
is INTERNAL_ONLY), links it to the Collector via HAS_COLLECTION_JOB through the standard
service-layer `create_edge`, then enqueues the Django Task that will execute
the registered collector class.

Per `req-tap-cares-collector-job-sole-writer`, the task body owns all
post-creation writes to CollectionJob — `run_collection` does not write to the
row again after handing off to `.enqueue()`.

Spec: req-tap-cares-collector-run-collection (spec-tap-cares-collector.md).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from django.db import transaction

from tap_auth.capabilities import WRITE_CAPABILITY
from tap_auth.enforcement import authorized, requires_capability
from tap_cares.collectors.readiness import (
    CollectorReadinessStatus,
    CollectorSelfTestResult,
    check_fail,
)
from tap_cares.exceptions import CollectorNotFoundError
from tap_cares.models import (
    CollectionJob,
    CollectionJobRunMode,
    CollectionJobStatus,
    Collector,
)
from tap_cares.registry import get_collector
from tap_cares.tasks import run_collector
from tap_grid.batch import close_batch, create_batch, fail_batch
from tap_grid.caller_context import CallerContext
from tap_grid.models import Batch, BatchStatus
from tap_grid.services import _create_node_internal, _patch_node_internal, create_edge

logger = logging.getLogger(__name__)

# `source` stamped on the batch that carries one CollectionJob's own lifecycle
# writes. The collector runtime is a named producer, so it names itself rather
# than falling through to the service layer's auto-created scaffolding
# (tap_grid.services._impl.AUTO_BATCH_SOURCE).
LIFECYCLE_BATCH_SOURCE = "tap_cares.collector"

# CollectionJob statuses at which the run is over and its lifecycle batch may be
# sealed. Anything else means the job is still in flight — or that the worker
# holding it died, which is unified-systems-com/tap#471's reconciliation to make,
# not this module's.
_TERMINAL_JOB_STATUSES = (
    CollectionJobStatus.SUCCESSFUL.value,
    CollectionJobStatus.FAILED.value,
)

# Gateway export manifest (spec-service-layer-boundary.md req-service-boundary-contract-surface):
# the reviewable list of gated operations, and nothing else. Every name here carries a
# capability gate — the service-boundary guard fails the build on any ungated entry, and on
# any ungated public function defined in a gateway module (this __init__ + the scheduler
# submodule) whether or not it is listed. The scheduler ops are defined in the scheduler
# gateway submodule and re-exported below.
__all__ = [
    # Collector-execution ops (defined here)
    "run_collection",
    "self_test_collector",
    "fire_collector_and_await",
    # Scheduler ops (defined in services/scheduler.py, re-exported below)
    "create_schedule",
    "set_schedule_enabled",
    "evaluate_tick",
]

# Loud, self-diagnosing detail for the RUNNER_UNAVAILABLE readiness failure.
# This failure is most often NOT a real misconfiguration: the Steady Queue
# supervisor is long-lived and forks workers from its boot-time memory image,
# and Steady Queue does not hot-reload (req-tap-cares-task-backend-deployment-3).
# A collector registered AFTER the supervisor booted is therefore absent from
# every worker it forks, surfacing here as a confusing mid-job failure on a
# collector that demonstrably works from a fresh `manage.py` process. Name the
# likely cause and the one-line fix at the point of failure rather than leaving
# the next operator to rediscover it. (Resolution stays trusted-startup only —
# this never imports from Collector node data; see
# req-tap-cares-collector-registry-6.)
_RUNNER_UNAVAILABLE_DETAIL = (
    "No collector runner is registered for {key!r} in this worker process. "
    "If this collector exists in the codebase, the most likely cause is a "
    "stale Steady Queue supervisor: it forks workers from its boot-time image "
    "and does not hot-reload (req-tap-cares-task-backend-deployment-3), so a "
    "collector registered after the supervisor started is absent from every "
    "worker it forks. Fix: restart the supervisor to pick up newly-registered "
    "collectors — `scripts/dc restart web`. If the collector genuinely does "
    "not exist in the codebase, this is a real Collector-node misconfiguration."
)
_RUNNER_UNAVAILABLE_SUMMARY = (
    "Collector runner is not registered in this worker process — most likely a "
    "stale Steady Queue supervisor; restart it: `scripts/dc restart web` "
    "(req-tap-cares-task-backend-deployment-3)."
)


@requires_capability("cares.self_test_collectors")
def self_test_collector(
    collector: Collector,
    *,
    caller_context: CallerContext | None = None,
) -> CollectorSelfTestResult:
    """Run a collector's readiness self-test and return a normalized result.

    Single caller-facing entry point (req-tap-cares-collector-self-test-11).
    Owns the cross-cutting concerns the pure hook deliberately excludes:
    registry resolution (`RUNNER_UNAVAILABLE`), exception trapping
    (`SELF_TEST_EXCEPTION`), stamping (`collector_registry` + `checked_at`),
    and the redaction-safe site-ID log summary.

    Returns the result synchronously; it does NOT write the grid. The
    run-task body records it onto `CollectionJob.self_test` and, on a
    non-runnable result, fails the job via the standard failure mode — that
    preserves the `CollectionJob` sole-writer invariant.
    """
    now = datetime.now(UTC)
    try:
        cls = get_collector(collector.collector_registry)
    except CollectorNotFoundError:
        result = CollectorSelfTestResult.from_checks(
            [
                check_fail(
                    "RUNNER_UNAVAILABLE",
                    _RUNNER_UNAVAILABLE_DETAIL.format(key=collector.collector_registry),
                    readiness_status=CollectorReadinessStatus.ERROR,
                    context={"collector_registry": collector.collector_registry},
                )
            ],
            summary=_RUNNER_UNAVAILABLE_SUMMARY,
            collector_registry=collector.collector_registry,
        )
    else:
        try:
            result = cls.self_test().with_collector_registry(collector.collector_registry)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[8797] collector_self_test_failed collector=%s registry=%s",
                collector.entity_id,
                collector.collector_registry,
            )
            result = CollectorSelfTestResult.from_checks(
                [
                    check_fail(
                        "SELF_TEST_EXCEPTION",
                        f"Collector self-test failed with {type(exc).__name__}: {exc}",
                        readiness_status=CollectorReadinessStatus.ERROR,
                        context={
                            "collector_registry": collector.collector_registry,
                            "exception_type": type(exc).__name__,
                        },
                    )
                ],
                summary="Collector self-test raised an exception.",
                collector_registry=collector.collector_registry,
            )

    # Stamp collector_registry + checked_at so every branch (success,
    # RUNNER_UNAVAILABLE, SELF_TEST_EXCEPTION) returns a self-describing
    # result carrying one authoritative instant
    # (req-tap-cares-collector-self-test-11, stamping).
    result = result.with_collector_registry(collector.collector_registry).with_checked_at(now)

    # One redaction-safe site-ID summary per invocation
    # (req-tap-cares-collector-self-test-8): INFO when runnable, WARNING
    # when not. Per-check detail is DEBUG only.
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for check in result.checks:
        counts[check.status.value] = counts.get(check.status.value, 0) + 1
    log = logger.info if result.runnable else logger.warning
    log(
        "[fa20] collector_self_test collector=%s registry=%s status=%s " "pass=%s warn=%s fail=%s skip=%s summary=%s",
        collector.entity_id,
        collector.collector_registry,
        result.status.value,
        counts["pass"],
        counts["warn"],
        counts["fail"],
        counts["skip"],
        result.summary,
    )
    return result


def _stamp_reconcile_config(lifecycle_batch: Batch, collector: Any) -> None:
    """Authority from the Collector node (off by default); budget from the node, else the
    collector class's ``RECONCILE_BUDGET_DEFAULT``, else 100 when the class cannot be resolved
    (that failure is reported by the run itself)."""
    from tap_cares.registry import get_collector
    from tap_grid.reconcile import stamp_run_config

    budget = getattr(collector, "reconcile_budget", None)
    if budget is None:
        try:
            budget = int(getattr(get_collector(collector.collector_registry), "RECONCILE_BUDGET_DEFAULT", 100))
        except Exception:  # noqa: BLE001 — an unresolvable class is the run's own failure, reported later
            budget = 100
    stamp_run_config(
        lifecycle_batch,
        authority=bool(getattr(collector, "reconcile_authority", False)),
        budget=budget,
        collector=str(collector.entity_id),
    )


def _open_lifecycle_batch(collector_label: str, now: datetime, ctx: CallerContext) -> Batch:
    """Open the one batch that carries a collection job's own lifecycle writes.

    A collection run's bookkeeping is one logical unit of work made of several
    writes spread across a task boundary — the `CollectionJob` node, its
    `HAS_COLLECTION_JOB` edge, the enqueue-side `task_result_id` patch, the
    RUNNING transition, the terminal patch, and the `PRODUCED_BATCH`
    correlation edges. They share this batch so a run reads back as one unit
    instead of four or five unrelated ones, none of them sealed
    (req-tap-cares-collector-run-collection-10).

    Deliberately NOT inherited from the caller: a caller-supplied batch scope is
    dropped for these writes because the run outlives its caller. The writes
    continue on a worker after `run_collection` has returned, so a caller's batch
    could never be sealed by the thing that finishes the work — which is the
    exact defect this opens a batch to fix. The scheduler already says this in
    prose at its `run_collection` call site; this is where it becomes mechanism.
    The GRIFT batch the collector imports is separate again, and stays separate:
    `grift_import` builds its own `CallerContext` per batch and ignores the
    ambient scope.

    `create_batch` writes an Entity and a Batch row, so it must sit inside a
    service-write scope. The collector trigger gate (`cares.run_collectors`) is
    not a write capability and does not open one, so authorize `grid.write`
    here — the same pattern `_open_fire_batch` uses in the scheduler.
    """
    from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor

    # `create_batch` reaches `create_entity`, which resolves its actor from the
    # ambient context rather than from an argument. Bind the collector actor
    # there too, so the batch's backing Entity is attributed to the same actor
    # `ctx` names — not to whoever happened to be bound by the surface that
    # triggered the run (a request user, on the Administrivia run button).
    with (
        acting_as(get_builtin_actor(COLLECTOR)),
        authorized(ctx, WRITE_CAPABILITY, operation="tap_cares.collector.open_lifecycle_batch"),
    ):
        return create_batch(
            name=f"Collection job lifecycle: {collector_label} @ {now.isoformat()}",
            description=(
                f"One collection run's own bookkeeping for {collector_label!r} enqueued at "
                f"{now.isoformat()}: the CollectionJob node, its HAS_COLLECTION_JOB edge, "
                f"the status transitions to terminal, and the PRODUCED_BATCH correlation "
                f"edges. The imported GRIFT batches are their own batches."
            ),
            source=LIFECYCLE_BATCH_SOURCE,
            actor=ctx.user,
        )


def _is_lifecycle_batch_of(batch_entity_id: str, job_entity_id: str, *, operation: str) -> bool:
    """True only if `batch_entity_id` is demonstrably `job_entity_id`'s lifecycle batch.

    The batch id reaches the worker in a task payload, beside a *separately
    supplied* job id. Nothing in that pairing is self-evident, so it is verified
    rather than trusted, from two facts the system already derives
    (req-tap-cares-collector-run-collection-16):

      1. `Batch.source` says the collector runtime produced this batch.
      2. `CollectionJob.batch_id` — the job's own spine row — says its writes rode
         this batch. `run_collection` creates the job *inside* the batch, so this
         holds from the moment the task can first see the row.

    Called at BOTH ends, and that is the point: the worker checks it before
    `acting_as(..., batch_id=...)` scopes any write, and the seal checks it again
    before closing anything. Checking only at the seal would refuse to close a
    foreign batch *after* having written a run's status patches and
    `PRODUCED_BATCH` edges into it — and a closed batch is not an append barrier,
    so those events would stay. One derivation, two call sites, no second copy of
    the rule.

    A mismatch is logged at ERROR with both sides named, and is the caller's cue
    to fail closed: run unscoped rather than write somewhere it does not belong.
    """
    if not batch_entity_id:
        return False
    try:
        batch = Batch.objects.get(entity_id=batch_entity_id)
        job = CollectionJob.objects.get(entity_id=job_entity_id)
    # PEP 758 (Python 3.14): an except clause may list exception types without
    # parentheses. This is valid, and black removes the parentheses if you write
    # them — noted because it reads as a pre-3.14 SyntaxError at a glance, and has
    # now been flagged as one by two independent reviewers.
    except Batch.DoesNotExist, CollectionJob.DoesNotExist:
        logger.error(
            "[cfde] collector: %s refused — batch %s or job %s does not exist",
            operation,
            batch_entity_id,
            job_entity_id,
        )
        return False
    if batch.source != LIFECYCLE_BATCH_SOURCE or str(job.batch_id) != str(batch_entity_id):
        logger.error(
            "[004e] collector: %s refused — batch %s has source %r (expected %r) and job %s "
            "records its batch as %r; this is not that job's lifecycle batch",
            operation,
            batch_entity_id,
            batch.source,
            LIFECYCLE_BATCH_SOURCE,
            job_entity_id,
            job.batch_id,
        )
        return False
    return True


def _fail_kickoff_batch(batch: Batch, ctx: CallerContext, reason: str) -> None:
    """Fail a lifecycle batch whose writes are never coming.

    Both kickoff failure paths land here — the synchronous one inside
    `run_collection`, and the deferred one in the `transaction.on_commit`
    callback, which runs after `run_collection` has returned when a caller
    wrapped it in its own transaction. A batch opened for work that will never
    happen must not be left `open` to read as a run in flight
    (req-tap-cares-collector-run-collection-13).

    Best-effort by construction: it must never mask the original failure, so a
    failure to fail is logged and swallowed.
    """
    from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor

    try:
        with (
            acting_as(get_builtin_actor(COLLECTOR)),
            authorized(ctx, WRITE_CAPABILITY, operation="tap_cares.collector.seal_lifecycle_batch"),
        ):
            batch.refresh_from_db()
            if batch.status == BatchStatus.OPEN:
                fail_batch(batch, reason)
    except Exception:
        logger.exception(
            "[b111] collector: could not fail lifecycle batch %s after a kickoff failure",
            batch.entity_id,
        )


def _seal_lifecycle_batch(batch_entity_id: str, job_entity_id: str) -> None:
    """Close (or fail) a job's lifecycle batch once the job is terminal.

    Level-triggered from observed state, never from the caller's belief about it:
    the job row is re-read and the batch is sealed only if that row says the run
    is over. `SUCCESSFUL` closes the batch; `FAILED` fails it carrying the job's
    own summary, so the batch and the job agree about how the run ended
    (req-tap-cares-collector-run-collection-11).

    **A non-terminal job leaves the batch open on purpose**
    (req-tap-cares-collector-run-collection-12). A worker pruned mid-run never
    reaches its terminal patch, so the job stays `RUNNING` and this batch stays
    `open` — the same orphan, observable the same way. That is
    unified-systems-com/tap#471's reconciliation to resolve, from the same
    authority that will move the job off `RUNNING`, and this module deliberately
    builds no second reaper to race it: two writers of terminal state is how the
    first one got lost. Until #471 lands, an `open` batch with
    `source = "tap_cares.collector"` whose `CollectionJob` is non-terminal is an
    interrupted run, and that is a truer signal than a batch some timer swept
    closed while the run may still have been alive.

    Fail-soft: this is bookkeeping. A seal that raises is logged at ERROR with
    the batch id and swallowed rather than being allowed to turn a completed
    collection into a failed task.
    """
    if not batch_entity_id:
        return
    from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor

    try:
        batch = Batch.objects.get(entity_id=batch_entity_id)
        if batch.status != BatchStatus.OPEN:
            return
        if not _is_lifecycle_batch_of(batch_entity_id, job_entity_id, operation="seal"):
            return
        job = CollectionJob.objects.get(entity_id=job_entity_id)
        if job.status not in _TERMINAL_JOB_STATUSES:
            logger.warning(
                "[fc56] collection job %s is %s, not terminal; its lifecycle batch %s stays open "
                "for reconciliation (unified-systems-com/tap#471)",
                job_entity_id,
                job.status,
                batch_entity_id,
            )
            return
        ctx = CallerContext(user=get_builtin_actor(COLLECTOR))
        with (
            acting_as(get_builtin_actor(COLLECTOR)),
            authorized(ctx, WRITE_CAPABILITY, operation="tap_cares.collector.seal_lifecycle_batch"),
        ):
            if job.status == CollectionJobStatus.FAILED.value:
                fail_batch(batch, job.summary or "Collection job failed.")
            else:
                close_batch(batch)
    except Exception:
        logger.exception(
            "[3a06] collector: could not seal lifecycle batch %s; it stays open",
            batch_entity_id,
        )


@requires_capability("cares.run_collectors")
def run_collection(
    collector: Collector,
    *,
    caller_context: CallerContext | None = None,
    manual_run: bool = False,
    manual_run_source: str = "",
    run_mode: str = CollectionJobRunMode.FULL,
) -> CollectionJob:
    """Start a collection run for the given Collector.

    Two authorization decisions, never collapsed (req-tap-auth-actor-model):

      1. **Trigger gate** — `@requires_capability("cares.run_collectors")` checks
         the *triggering* actor: the request user (passed through from tap_web's
         middleware-bound `CallerContext`), the `tap_cares.scheduler` on a tick, or
         the `tap_bootloader` firing boot collectors. tap_web is a pure pass-through
         here — it adds no actor of its own; it hands its request context to this
         service, which confirms that actor may run collectors.
      2. **Execution identity** — the collection itself then runs as the
         least-privilege `tap_cares.collector` program actor (the swap below), never
         as the triggering actor, so the collector's blast radius is bounded
         regardless of who triggered it (the Kubernetes-CronJob ServiceAccount
         model).

    `run_collection` is the sole creator of `CollectionJob` rows
    (req-tap-cares-collector-job-model-18). `run_mode` selects the vehicle:
    `full` (phase 1 → phase 2 if runnable) or `self_test_only` (phase 1 →
    stop) — a one-off readiness probe is just a `self_test_only` job on the
    same async path (req-tap-cares-collector-self-test-16). Manual Run and
    the scheduler use the default `full`.

    Performs, in order:
      0. Opens the one batch that carries this run's own lifecycle writes
         (`_open_lifecycle_batch`), so the node, the edge, the status
         transitions and the `PRODUCED_BATCH` edges read back as one unit of
         work rather than four unsealed ones
         (req-tap-cares-collector-run-collection-10). A caller-supplied batch
         scope is deliberately not inherited for these writes — the run
         outlives its caller, so only the run can seal them. The GRIFT batches
         the collector imports stay separate; `grift_import` scopes each to
         itself.
      1. Creates a CollectionJob node via `_create_node_internal`
         (CollectionJob is INTERNAL_ONLY), persisting `manual_run`,
         `manual_run_source`, and `run_mode` on the row
         (req-tap-cares-collector-run-collection-9).
      2. Creates a HAS_COLLECTION_JOB edge from collector.entity to the new job via
         `tap_grid.services.create_edge`.
      3. Enqueues the `run_collector` Django Task with the JSON-safe
         collector + job + lifecycle-batch entity IDs. The batch id rides the
         task payload because the remaining lifecycle writes happen in the
         worker, across a task boundary a context manager cannot span.
      4. Returns the CollectionJob in its post-enqueue state.

    Manual surfaces (Administrivia run button today) call with
    `manual_run=True` and a short `manual_run_source` identifier. Scheduler
    invocations leave both at defaults; the scheduler-trigger relationship
    is recorded by the inbound `ScheduleFire --TRIGGERED_JOB--> CollectionJob`
    edge (req-tap-cares-scheduler-trigger-provenance-2).

    With ImmediateBackend (v0 default) the returned job will already reflect
    the terminal task outcome by the time this function returns; with a worker
    backend the job will be READY or RUNNING depending on worker pickup
    latency.
    """
    # Collection ALWAYS runs as the least-privilege tap_cares.collector program actor —
    # never as the human or schedule that triggered it (model 2: own service
    # identity, like a Kubernetes CronJob's ServiceAccount). The trigger is
    # recorded as metadata (manual_run / manual_run_source; the schedule's
    # HAS_FIRED/TRIGGERED_JOB provenance), not as the runtime principal, so the
    # collector's blast radius is bounded regardless of who set it up. A batch
    # scope the caller supplied is NOT kept: the run's lifecycle writes get their
    # own batch below, because they outlive the caller and only the run can seal
    # them (req-tap-cares-collector-run-collection-10). (req-tap-auth-actor-model;
    # the on-behalf-of delegation alternative is deferred —
    # req-tap-auth-ai-placeholder.)
    from tap_auth.actors import COLLECTOR, get_builtin_actor

    ctx = CallerContext(user=get_builtin_actor(COLLECTOR))
    now = datetime.now(UTC)

    if run_mode not in CollectionJobRunMode.values:
        raise ValueError(
            f"run_collection: invalid run_mode {run_mode!r}; " f"expected one of {CollectionJobRunMode.values}."
        )
    # Normalize enum-member or string input to the canonical stored string,
    # mirroring how `status` is persisted as its `.value`.
    run_mode = CollectionJobRunMode(run_mode).value

    collector_label = collector.name or "Collection"
    if run_mode == CollectionJobRunMode.SELF_TEST_ONLY:
        description = f"Self-test-only run of {collector_label!r} enqueued at {now.isoformat()}."
    elif manual_run and manual_run_source:
        description = f"Manual run of {collector_label!r} triggered from " f"{manual_run_source} at {now.isoformat()}."
    elif manual_run:
        description = f"Manual run of {collector_label!r} at {now.isoformat()}."
    else:
        description = f"Collection run of {collector_label!r} enqueued at {now.isoformat()}."

    # One batch for this run's own lifecycle writes, opened before the first of
    # them so every one of them lands in it — including the ones a worker makes
    # after this function has returned (req-tap-cares-collector-run-collection-10).
    lifecycle_batch = _open_lifecycle_batch(collector_label, now, ctx)
    lifecycle_batch_entity_id = str(lifecycle_batch.entity_id)
    # The run's reconcile configuration is stamped here, before any collector code runs, from
    # the Collector node's operator-set fields (req-grid-reconcile-verb-2/-3). The verb reads
    # authority and budget from this stamp and nowhere else.
    _stamp_reconcile_config(lifecycle_batch, collector)
    ctx = CallerContext(user=ctx.user, batch_id=lifecycle_batch_entity_id)

    try:
        job_create = _create_node_internal(
            "collection_job",
            {
                "name": f"{collector_label} {now.isoformat()}",
                "description": description,
                "status": CollectionJobStatus.READY.value,
                "run_mode": run_mode,
                "enqueued_at": now.isoformat(),
                "manual_run": manual_run,
                "manual_run_source": manual_run_source,
            },
            caller_context=ctx,
        )
        if not job_create.success:
            raise RuntimeError(
                f"run_collection: CollectionJob create failed: " f"{[(e.code, e.message) for e in job_create.errors]}"
            )

        job = CollectionJob.objects.get(entity_id=job_create.entity_id)

        create_edge(
            from_entity=collector.entity,
            to_entity=job.entity,
            edge_type="HAS_COLLECTION_JOB",
            caller_context=ctx,
        )

        # Defer the enqueue until any surrounding transaction commits, so the
        # Steady Queue worker (on a separate DB connection) never picks up a
        # task whose CollectionJob row hasn't been flushed yet
        # (req-tap-cares-task-backend-transactional-integrity-1). With no
        # outer transaction in progress, transaction.on_commit fires the
        # callback immediately — preserving current behavior for the
        # Administrivia handlers and scheduler Stage 2 call sites.
        #
        # Also captures task_result.id from the returned TaskResult and
        # patches it onto CollectionJob.task_result_id. We do it on the
        # enqueue side rather than from inside run_collector because
        # Steady Queue 0.2.0 doesn't honor takes_context=True; see the
        # comment on run_collector in tap_cares/tasks.py.
        collector_entity_id = str(collector.entity_id)
        job_entity_id = str(job.entity_id)

        def _enqueue_and_record_task_id() -> None:
            # This callback runs on the OTHER side of the commit when a caller
            # wrapped `run_collection` in its own `transaction.atomic()` — after
            # this function has returned, so the kickoff-failure handler below is
            # no longer on the stack. An enqueue that raises there would strand a
            # committed, empty, `open` batch with no task ever coming: the exact
            # state this change exists to eliminate. Seal it here too
            # (req-tap-cares-collector-run-collection-13), then re-raise so the
            # failure still surfaces.
            try:
                task_result = run_collector.enqueue(collector_entity_id, job_entity_id, lifecycle_batch_entity_id)
            except Exception as exc:
                # ONLY an enqueue failure fails the batch. Past this line the task
                # is accepted and the run is live, so the batch must stay open for
                # the worker to seal — failing it here would hand a SUCCESSFUL job
                # a permanently FAILED batch, which is the disagreement this whole
                # change exists to prevent, and the seal cannot correct it because
                # a non-OPEN batch is left alone.
                _fail_kickoff_batch(lifecycle_batch, ctx, f"enqueue failed after commit: {type(exc).__name__}: {exc}")
                raise
            if task_result.id:
                # The request/task context has been torn down by now, so the
                # ambient actor is gone. Pass the resolved tap_cares.collector
                # ctx explicitly so this bookkeeping write still binds a named
                # actor (the on-commit analogue of the prod-break the task-body
                # acting_as binding closes).
                try:
                    _patch_node_internal(job_entity_id, {"task_result_id": task_result.id}, caller_context=ctx)
                except Exception:
                    # Correlation metadata for an already-running task. Nothing
                    # depends on it — the sole-writer invariant means the task body
                    # never reads it — so a failure here is logged, not escalated
                    # into a failed batch or a failed enqueue.
                    logger.exception(
                        "[04dc] collector: could not record task_result_id on job %s; the run is unaffected",
                        job_entity_id,
                    )

        transaction.on_commit(_enqueue_and_record_task_id)
    except Exception as exc:
        # The batch was opened for writes that are now never coming. Fail it
        # carrying the reason rather than leaving an empty `open` batch behind
        # to be mistaken for a run in flight (req-tap-cares-collector-run-collection-13).
        # Best-effort and never masks the original failure.
        _fail_kickoff_batch(lifecycle_batch, ctx, f"run_collection failed before enqueue: {type(exc).__name__}: {exc}")
        raise

    # Refresh once to pick up whatever terminal state the task body wrote
    # under ImmediateBackend. Under a worker backend the row may still be in
    # READY or RUNNING at this point; either way we return the latest visible
    # state. We do NOT write to the row here — that would violate the
    # sole-writer invariant (req-tap-cares-collector-job-sole-writer).
    job.refresh_from_db()
    return job


@requires_capability("cares.run_collectors")
def fire_collector_and_await(
    collector: Collector,
    *,
    caller_context: CallerContext | None = None,
    run_mode: str = CollectionJobRunMode.FULL,
    manual_run_source: str = "boot",
    timeout_seconds: float = 600.0,
    poll_interval_seconds: float = 2.0,
) -> tuple[bool, CollectionJob]:
    """Fire one collector via `run_collection` and block until its job is terminal.

    The reusable fire-collector mechanic shared by `tap_boot`'s population phase
    (`fire-collector` step, req-boot-population) and the dev `fire_boot_collectors`
    command. A real Steady Queue worker drains the job out-of-process, so this
    polls `CollectionJob.status` to a terminal state rather than reading an inline
    result; under ImmediateBackend the first check already sees the terminal state.

    Boot-agnostic: it inherits the ambient actor context the caller bound (the
    trigger gate checks that actor; the collection itself swaps to
    `tap_cares.collector` inside `run_collection`). Returns `(succeeded, job)` —
    `succeeded` is True iff the job reached SUCCESSFUL within `timeout_seconds`.
    """
    job = run_collection(
        collector,
        caller_context=caller_context,
        manual_run=True,
        manual_run_source=manual_run_source,
        run_mode=run_mode,
    )

    terminal = (CollectionJobStatus.SUCCESSFUL.value, CollectionJobStatus.FAILED.value)
    deadline = time.monotonic() + timeout_seconds
    while True:
        job.refresh_from_db()
        if job.status in terminal:
            break
        if time.monotonic() >= deadline:
            return False, job
        time.sleep(poll_interval_seconds)

    return job.status == CollectionJobStatus.SUCCESSFUL.value, job


# Scheduler gateway ops live in the scheduler submodule (they carry a large body of
# below-gate helpers). Re-exported here so `__all__` advertises the whole gateway surface
# from one place and callers use `from tap_cares.services import evaluate_tick`. Imported at
# the bottom, after the collector ops above are defined, so scheduler.py's own lazy
# `run_collection` import resolves against a fully-initialized package.
from tap_cares.services.scheduler import (  # noqa: E402
    create_schedule,
    evaluate_tick,
    set_schedule_enabled,
)
