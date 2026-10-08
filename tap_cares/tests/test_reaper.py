"""Tests for tap_cares.services.reaper (req-tap-cares-collector-job-reaper, tap#471).

Constructs steady_queue's own tables directly (`Job`, `ClaimedExecution`,
`Process`, `FailedExecution`) rather than running a real worker: this is the
same shape a live orphaning takes, and it is the only way to exercise the
"claim exists but its process stopped heartbeating" branch without an actual
dead process to wait out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone

from tap_cares.models import CollectionJob, CollectionJobStatus, Collector
from tap_cares.services.reaper import _reap_stale_collection_jobs
from tap_grid.write_guard import unguarded_write


def _make_collector(suffix: str = "") -> Collector:
    return Collector.objects.create(  # type: ignore[no-any-return]
        name=f"Test Collector {suffix}".strip(),
        description="",
        collector_registry=f"tap_cares.tests.fakes:dummy-{suffix or 'x'}",
    )


def _make_running_job(*, task_result_id: str, started_at: datetime | None = None) -> CollectionJob:
    return CollectionJob.objects.create(  # type: ignore[no-any-return]
        name="Test Job",
        description="fixture",
        status=CollectionJobStatus.RUNNING,
        task_result_id=task_result_id,
        started_at=started_at or timezone.now(),
    )


def _make_steady_queue_job(pk: int | None = None, finished_at: datetime | None = None) -> Any:
    from steady_queue.models import Job

    job = Job(
        queue_name="default",
        class_name="tap_cares.tasks.run_collector",
        arguments={"args": [], "kwargs": {}},
        finished_at=finished_at,
    )
    if pk is not None:
        job.pk = pk
    job.save()
    return job


def _make_process(*, last_heartbeat_at: datetime, pid: int = 12345, name: str = "worker-test") -> Any:
    from steady_queue.models import Process

    return Process.objects.create(
        kind="worker",
        last_heartbeat_at=last_heartbeat_at,
        pid=pid,
        name=name,
    )


def _claim(job: Any, process: Any = None) -> Any:
    from steady_queue.models import ClaimedExecution

    return ClaimedExecution.objects.create(job=job, process=process)


def _fail(job: Any, error: str = "boom") -> Any:
    from steady_queue.models import FailedExecution

    return FailedExecution.objects.create(job=job, error=error)


@pytest.mark.django_db
class TestReapStaleCollectionJobs:
    def test_only_running_jobs_are_considered(self):
        """A SUCCESSFUL or FAILED row is never touched, whatever its task_result_id says."""
        CollectionJob.objects.create(
            name="done", description="", status=CollectionJobStatus.SUCCESSFUL, task_result_id="999999"
        )
        assert _reap_stale_collection_jobs() == []

    def test_live_claim_with_recent_heartbeat_is_left_alone(self):
        """The core non-reap case: a real worker is genuinely still working on it."""
        job = _make_running_job(task_result_id="1")
        steady_job = _make_steady_queue_job(pk=1)
        process = _make_process(last_heartbeat_at=timezone.now())
        _claim(steady_job, process)

        assert _reap_stale_collection_jobs() == []
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.RUNNING

    def test_stale_heartbeat_is_reaped_with_pid_and_time_named(self):
        """The tap#471 shape: a container restart kills the process, the claim outlives it."""
        job = _make_running_job(task_result_id="2")
        steady_job = _make_steady_queue_job(pk=2)
        stale_at = timezone.now() - timedelta(minutes=10)
        process = _make_process(last_heartbeat_at=stale_at, pid=301)
        _claim(steady_job, process)

        reaped = _reap_stale_collection_jobs()

        assert reaped == [str(job.entity_id)]
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        assert job.summary.startswith("Reaped:")
        assert "301" in job.summary
        assert job.finished_at is not None

    def test_steady_queue_failed_execution_is_reaped_with_its_error(self):
        """steady_queue's own maintenance already caught this one; nobody read it."""
        job = _make_running_job(task_result_id="3")
        steady_job = _make_steady_queue_job(pk=3)
        _fail(steady_job, error="ProcessPrunedError: 2026-01-01T00:00:00+00:00")

        reaped = _reap_stale_collection_jobs()

        assert reaped == [str(job.entity_id)]
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        assert "ProcessPrunedError" in job.summary

    def test_steady_queue_has_no_record_at_all_is_reaped(self):
        """The steady_queue Job row itself was pruned (or the id never matched one)."""
        job = _make_running_job(task_result_id="999999")

        reaped = _reap_stale_collection_jobs()

        assert reaped == [str(job.entity_id)]
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        assert "999999" in job.summary

    def test_steady_queue_says_finished_but_row_never_patched_is_reaped(self):
        """Finished per steady_queue, but no terminal write ever landed on the CollectionJob."""
        job = _make_running_job(task_result_id="4")
        _make_steady_queue_job(pk=4, finished_at=timezone.now())

        reaped = _reap_stale_collection_jobs()

        assert reaped == [str(job.entity_id)]
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        assert "never patched" in job.summary

    def test_unresolvable_task_result_id_within_timeout_is_left_alone(self):
        """A non-numeric id (e.g. an immediate/dummy backend's 32-char string) is not itself
        a failure — the flat-age backstop, not an exception, governs it."""
        job = _make_running_job(task_result_id="not-a-steady-queue-id", started_at=timezone.now())

        assert _reap_stale_collection_jobs() == []
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.RUNNING

    def test_unresolvable_task_result_id_past_timeout_is_reaped(self):
        """The same case, old enough that nothing will ever resolve it — the age backstop fires."""
        job = _make_running_job(
            task_result_id="not-a-steady-queue-id",
            started_at=timezone.now() - timedelta(minutes=45),
        )

        reaped = _reap_stale_collection_jobs()

        assert reaped == [str(job.entity_id)]
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        assert "reap timeout" in job.summary

    def test_empty_task_result_id_past_timeout_is_reaped(self):
        """No task was ever enqueued for this row at all (req-tap-cares-collector-job-model-6)."""
        job = _make_running_job(task_result_id="", started_at=timezone.now() - timedelta(minutes=45))

        reaped = _reap_stale_collection_jobs()

        assert reaped == [str(job.entity_id)]

    def test_multiple_stale_rows_are_all_reaped_in_one_call(self):
        """The exact shape from 2026-09-26: a restart mid-collection orphaned more than one run."""
        job_a = _make_running_job(task_result_id="5")
        _make_process_and_claim_stale(job_a, steady_pk=5, pid=10)
        job_b = _make_running_job(task_result_id="6")
        _make_process_and_claim_stale(job_b, steady_pk=6, pid=11)

        reaped = _reap_stale_collection_jobs()

        assert set(reaped) == {str(job_a.entity_id), str(job_b.entity_id)}

    def test_a_row_resolved_between_scan_and_write_is_not_overwritten(self):
        """The TOCTOU this exists to close (Grok, PR# 845 - tap): the real task body can
        complete — and write its own terminal patch — at any point between the RUNNING
        scan and this function's write. A row no longer RUNNING when re-read must be left
        exactly as its own writer left it, not stomped with a false `Reaped: ...`."""
        from unittest.mock import patch as mock_patch

        from tap_cares.services import reaper as reaper_module

        job = _make_running_job(task_result_id="7")
        steady_job = _make_steady_queue_job(pk=7)
        stale_process = _make_process(last_heartbeat_at=timezone.now() - timedelta(minutes=10), pid=20)
        _claim(steady_job, stale_process)

        # Simulate the real task body winning the race: by the time this function's
        # write path re-reads the row, it has already reached a terminal state.
        real_dead_reason = reaper_module._dead_reason

        def _resolve_then_decide(j):
            reason = real_dead_reason(j)
            CollectionJob.objects.filter(entity_id=j.entity_id).update(
                status=CollectionJobStatus.SUCCESSFUL, summary="Collected 3 repo(s): real success"
            )
            return reason

        with mock_patch("tap_cares.services.reaper._dead_reason", side_effect=_resolve_then_decide):
            reaped = _reap_stale_collection_jobs()

        assert reaped == []
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert job.summary == "Collected 3 repo(s): real success"

    @pytest.mark.django_db(transaction=True)
    def test_the_write_lock_is_actually_held_through_the_reap_write(self):
        """The test above patches the row inside `_dead_reason`, before
        `_reap_if_still_running` ever takes `select_for_update()` — so it never
        exercises whether the lock actually covers the write (Grok, PR# 845 - tap,
        round 4: 'a real test would overlap an UPDATE of the same PK after the
        lock is taken, not during `_dead_reason`'). This one does exactly that,
        with a second real thread on its own DB connection: a concurrent write on
        the same row, issued only once the lock is confirmed held, must block
        until this transaction commits, and its own write must be what's left
        standing afterward — not a stomped reap. `transaction=True` on this test
        alone (the class default shares one connection per test, which can't show
        cross-connection blocking) is what makes real concurrency possible here.
        """
        import threading
        import time as time_module
        from unittest.mock import patch as mock_patch

        from django.db import close_old_connections, connection

        from tap_cares.services import reaper as reaper_module

        job = _make_running_job(task_result_id="11")

        real_reap_by_id = reaper_module._reap_by_id
        lock_acquired = threading.Event()
        hold_seconds = 0.4

        def _slow_reap_by_id(entity_id, reason):
            lock_acquired.set()
            time_module.sleep(hold_seconds)
            real_reap_by_id(entity_id, reason)

        outcome: dict[str, float] = {}

        def _concurrent_real_write() -> None:
            close_old_connections()
            assert lock_acquired.wait(timeout=5), "reap never signalled it took the lock"
            started = time_module.monotonic()
            # A fixture standing in for another worker's write. Context variables do not cross
            # into a new thread, so the harness's write hatch is opened here explicitly.
            with unguarded_write():
                CollectionJob.objects.filter(entity_id=job.entity_id).update(
                    status=CollectionJobStatus.SUCCESSFUL, summary="real success, arrived mid-reap"
                )
            outcome["elapsed"] = time_module.monotonic() - started
            connection.close()

        writer_thread = threading.Thread(target=_concurrent_real_write)
        writer_thread.start()

        with mock_patch("tap_cares.services.reaper._reap_by_id", side_effect=_slow_reap_by_id):
            reaper_module._reap_if_still_running(job.entity_id, "test reason")

        writer_thread.join(timeout=5)
        assert not writer_thread.is_alive(), "the concurrent writer never returned"
        assert outcome.get("elapsed", 0) >= hold_seconds * 0.8, (
            "the concurrent UPDATE returned before the reap released its lock — "
            "select_for_update() is not actually blocking a real writer"
        )

        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert job.summary == "real success, arrived mid-reap"

    def test_one_bad_row_does_not_stop_the_rest_of_the_sweep(self):
        """A row that raises while being evaluated is logged and skipped, not left to
        cancel the whole tick — the reaper sits ahead of every schedule's own evaluation,
        so an unhandled exception here would cancel every fire behind it too."""
        from unittest.mock import patch as mock_patch

        from tap_cares.services import reaper as reaper_module

        good_job = _make_running_job(task_result_id="8")
        _make_process_and_claim_stale(good_job, steady_pk=8, pid=30)
        bad_job = _make_running_job(task_result_id="9")
        _make_process_and_claim_stale(bad_job, steady_pk=9, pid=31)

        real_dead_reason = reaper_module._dead_reason

        def _raise_for_bad_job(j):
            if str(j.entity_id) == str(bad_job.entity_id):
                raise RuntimeError("simulated unexpected shape")
            return real_dead_reason(j)

        with mock_patch("tap_cares.services.reaper._dead_reason", side_effect=_raise_for_bad_job):
            reaped = _reap_stale_collection_jobs()

        assert reaped == [str(good_job.entity_id)]
        bad_job.refresh_from_db()
        assert bad_job.status == CollectionJobStatus.RUNNING


def _make_process_and_claim_stale(job: CollectionJob, *, steady_pk: int, pid: int) -> None:
    steady_job = _make_steady_queue_job(pk=steady_pk)
    process = _make_process(last_heartbeat_at=timezone.now() - timedelta(minutes=10), pid=pid)
    _claim(steady_job, process)
