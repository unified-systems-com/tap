"""Reconcile a stale `RUNNING` CollectionJob left behind by a dead worker.

`unified-systems-com/tap#471`: when a steady_queue worker dies mid-task (a
container restart, a connection-exhaustion prune), `run_collector`'s own
terminal-state patch never runs, so the `CollectionJob` row it opened sits at
`RUNNING` forever. The scheduler's single-flight guard
(`req-tap-cares-scheduler-concurrency-2`) then reads that row as "still
active" and refuses every subsequent fire, correctly given what the row
says — the row is what is wrong, not the guard. Occurred three times
(2026-09-11, 2026-09-15, 2026-09-26) before this existed.

This is the "separate stuck-job sweep" `req-tap-cares-collector-job-sole-writer-7`
names as future, out-of-scope work, and the one deliberate exception to the
sole-writer invariant (`req-tap-cares-collector-job-sole-writer-2`): after
`run_collection` returns, the task body is the only writer *while the task is
actually alive*. This module is the reconciler for when it is not — it never
races the task body, because deriving "dead" (below) is only ever true once
the task body can no longer run.

Derive, don't trust (the house order, tap#471's remedy):
    steady_queue's own `FailedExecution` / `Job.finished_at` already hold the
    truth about the underlying task; nobody read them before this. A row with
    no resolvable task record at all, or one whose task record itself is
    stale past `_STALE_RUNNING_TIMEOUT` with no live claim, is the fallback —
    covers a `task_result_id` steady_queue never recognized, or a backend
    that does not use steady_queue's job table shape at all.

TAP-IMPLEMENTS: req-tap-cares-collector-job-reaper@0bd4cad8499a/02fcc9ff4544 (derivation) —
    the reconciler itself: every derive step in `_dead_reason`, the flat-age
    backstop in `_timeout_reason`, the re-check-before-write in
    `_reap_if_still_running`, and the terminal patch in `_reap_by_id`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from django.db import transaction

from tap_cares.models import CollectionJob, CollectionJobStatus

logger = logging.getLogger(__name__)

# A RUNNING job past this age with no live steady_queue claim is reaped even
# when its task record can't be resolved at all — the backstop for a
# task_result_id steady_queue never recognized (a different task backend, or
# a row from before this reconciliation existed).
_STALE_RUNNING_TIMEOUT = timedelta(minutes=30)


def _reap_stale_collection_jobs() -> list[str]:
    """Reconcile every `RUNNING` CollectionJob whose owning task is actually dead.

    Called once per scheduler tick (`evaluate_tick`), before any schedule's
    `_active_run_count` is read — so a tick that reaps a stale row and a tick
    that fires a new run off the freed slot can be the same tick. Also
    effectively covers "at startup": the scheduler's first tick fires within
    a minute of the container coming up.

    Returns the `entity_id` of each row reaped, for the caller to log at the
    tick level (a single-line count) rather than duplicating the per-row
    detail this function already logs at ERROR.

    Never raises: this call sits ahead of every schedule's own evaluation in
    `evaluate_tick`, so an exception here — a row shaped unexpectedly, a
    steady_queue read failing — must not cancel that tick's fires along with
    it. One bad row is logged and skipped; the rest of the sweep, and the
    schedules waiting behind it, still run.
    """
    reaped: list[str] = []
    for job in CollectionJob.objects.filter(status=CollectionJobStatus.RUNNING.value):
        try:
            reason = _dead_reason(job)
            if reason is not None and _reap_if_still_running(job.entity_id, reason):
                reaped.append(str(job.entity_id))
        except Exception:
            logger.exception("[c7f4] reap check failed for CollectionJob %s; leaving it RUNNING", job.entity_id)
    return reaped


def _reap_if_still_running(entity_id: uuid.UUID, reason: str) -> bool:
    """Lock the row, re-check it, and only reap if it is still RUNNING.

    Closes the gap between the queryset snapshot `_reap_stale_collection_jobs`
    iterates and the write below: the real task body can complete — and write
    its own terminal patch — at any point in between, on its own worker,
    concurrently with this sweep. A plain re-read immediately before the write
    narrows that gap but does not close it (Grok, PR# 845 - tap, round 3): the
    task body's own write could still land in the instant between this
    function's read and `_reap_by_id`'s write, and be overwritten by a false
    `Reaped: ...`.

    `select_for_update()` closes it for real: it takes a row lock for the rest
    of this transaction, so the task body's own patch (an `UPDATE` by the same
    primary key, however it gets there) blocks on this row until this
    transaction commits or rolls back, rather than interleaving with it. Two
    orders remain, both correct — the task body wrote first and this
    transaction's re-check sees its terminal status and backs off; or this
    transaction wins the lock first, reaps, and commits, and the task body's
    write is queued behind it and lands after — overwriting the reap with the
    real terminal state, which is what should win.
    """
    with transaction.atomic():
        current = (
            CollectionJob.objects.select_for_update()
            .filter(entity_id=entity_id)
            .values_list("status", flat=True)
            .first()
        )
        if current != CollectionJobStatus.RUNNING.value:
            logger.info(
                "[8a63] CollectionJob %s resolved to %s between the reap scan and the write; not reaping",
                entity_id,
                current,
            )
            return False
        _reap_by_id(entity_id, reason)
    return True


def _dead_reason(job: CollectionJob) -> str | None:
    """The stated reason this RUNNING row is actually dead, or None to leave it alone."""
    import steady_queue as steady_queue_config
    from django.utils import timezone
    from steady_queue.models import ClaimedExecution, FailedExecution, Job

    task_id = _steady_queue_job_id(job.task_result_id)
    if task_id is None:
        return _timeout_reason(job)

    steady_job = Job.objects.filter(pk=task_id).first()
    if steady_job is None:
        # Not a startup-visibility race (Grok, PR# 845 - tap, rounds 3-4): the
        # enqueue side (`tap_cares/services/__init__.py::_enqueue_and_record_task_id`)
        # creates this `Job` row synchronously and only patches `task_result_id`
        # onto CollectionJob *after* `enqueue()` returns; `status` only becomes
        # RUNNING later still, when a worker claims and starts the task. A `RUNNING`
        # row can therefore never observe a missing `Job` row for a task that is
        # actually still alive — a missing row here means the task genuinely
        # finished (and its row was pruned, if `preserve_finished_jobs` is off) or
        # the enqueue itself never happened.
        return f"steady_queue has no job record for task {job.task_result_id} (pruned, or never enqueued through it)"

    failure = FailedExecution.objects.filter(job_id=steady_job.pk).first()
    if failure is not None:
        # Not a race against a live claim either: `ClaimedExecution.job` is a
        # `OneToOneField`, and both `ClaimedExecution.finished()` and
        # `.failed_with()` delete the claim in the same atomic transaction that
        # finalizes the Job or creates this FailedExecution row — a live claim and
        # a FailedExecution for the same job cannot coexist at any observable
        # instant, so checking this before the claim/heartbeat branch is safe.
        return f"steady_queue recorded this task failed: {failure.error}"

    if steady_job.finished_at is not None:
        # steady_queue's own bookkeeping says the task finished, but nothing ever
        # patched the CollectionJob to a terminal state — a body that raised past
        # its own `except`, or died between `ClaimedExecution.finished()` and the
        # next tick. Distinct from the ProcessPrunedError case above.
        return "steady_queue recorded this task as finished, but the CollectionJob row was never patched to a terminal state"

    claim = ClaimedExecution.objects.filter(job_id=steady_job.pk).select_related("process").first()
    if claim is None:
        # Not yet claimed at all (still queued behind other work) — fall through
        # to the timeout backstop rather than treat "unclaimed" as "dead".
        return _timeout_reason(job)

    if claim.process is None:
        return "steady_queue's claim on this task has no process (deregistered) but was never reconciled"

    # Same definition steady_queue's own Maintenance uses to decide a process is
    # prunable (steady_queue.models.prunable.PrunableQuerySet.prunable) — derived
    # from its one constant rather than a second copy of the threshold, and
    # checked here on every tick rather than waiting for that maintenance timer's
    # own cadence (process_alive_threshold itself, staggered from whenever the
    # current supervisor started) to get around to it.
    stale_before = timezone.now() - steady_queue_config.process_alive_threshold
    if claim.process.last_heartbeat_at < stale_before:
        return (
            f"steady_queue's claiming process (pid {claim.process.pid}) last heartbeat "
            f"{claim.process.last_heartbeat_at.isoformat()}, past the "
            f"{steady_queue_config.process_alive_threshold} alive threshold"
        )
    return None  # genuinely claimed by a live, heartbeating process


def _steady_queue_job_id(task_result_id: str) -> int | None:
    """`CollectionJob.task_result_id` as a steady_queue `Job` primary key, or None.

    `task_result_id` is a bare string by contract (req-tap-cares-collector-job-model)
    because Django Tasks lets a backend choose its own id shape; steady_queue's is a
    stringified integer PK, but the field exists to accommodate others too (the
    immediate/dummy backends use 32-char random strings). A non-numeric id means
    steady_queue's tables have nothing to say about this row — the timeout backstop
    handles it, not an exception here.
    """
    if not task_result_id:
        return None
    try:
        return int(task_result_id)
    except ValueError:
        return None


def _timeout_reason(job: CollectionJob) -> str | None:
    started = job.started_at or job.entity.created_at
    if started is None:
        return None
    age = datetime.now(UTC) - started
    if age > _STALE_RUNNING_TIMEOUT:
        return f"RUNNING for {age} (over the {_STALE_RUNNING_TIMEOUT} reap timeout) with no live steady_queue claim"
    return None


def _reap_by_id(entity_id: uuid.UUID, reason: str) -> None:
    """Patch one dead `RUNNING` row to FAILED, through the same write path the task body uses.

    Takes the id rather than a `CollectionJob` instance on purpose: the caller
    (`_reap_if_still_running`) has just re-read the row fresh to confirm it is
    still RUNNING, and passing that stale instance back in here would reopen
    the exact TOCTOU window the re-read exists to close.
    """
    from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
    from tap_cares.tasks import _patch_job

    logger.error("[a1e9] reaping stale CollectionJob %s: %s", entity_id, reason)
    with acting_as(
        get_builtin_actor(COLLECTOR),
        batch_name="Stale CollectionJob reap",
        batch_description=f"Reconciling CollectionJob {entity_id}, orphaned by a dead worker: {reason}",
    ):
        _patch_job(
            str(entity_id),
            {
                "status": CollectionJobStatus.FAILED.value,
                "finished_at": datetime.now(UTC).isoformat(),
                "summary": f"Reaped: {reason}",
            },
        )
