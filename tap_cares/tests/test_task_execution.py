"""Tests for the Django Tasks-backed collector execution runtime.

Covers req-tap-cares-collector-task-execution and the lifecycle-update ACIDs
on the CollectionJob (req-tap-cares-collector-job-lifecycle-2, -3, -4) that
land with the runtime.

Uses Django's ImmediateBackend (configured in tap/settings.py), so enqueue()
runs the task synchronously and the CollectionJob has its terminal state by
the time run_collection returns.
"""

from __future__ import annotations

import pytest

from tap_cares.collectors.config import CollectorConfig
from tap_cares.models import CollectionJobStatus, Collector
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import run_collection
from tap_cares.tests.fakes import BoomCollector, HappyCollector


@pytest.fixture(autouse=True)
def reset_happy_runs():
    HappyCollector.runs.clear()
    yield
    HappyCollector.runs.clear()


def _register_and_fetch(key: str, cls, scope: str, *, name: str = "Test Collector") -> Collector:
    """Register a collector and fetch the resulting on-grid Collector node.

    Replaces the v0-pre-refactor pattern of `Collector.objects.create(...)` —
    `register_collector` now performs the on-grid upsert as part of the
    dual-existence registration. Tests fetch the resulting node by its
    canonical `collector_registry` value.
    """
    register_collector(
        key=key,
        cls=cls,
        scope=scope,
        name=name,
        description="Fixture collector for tap_cares.tests.test_task_execution.",
    )
    # register_collector is read-only at runtime (ready-readonly); the on-grid node
    # is materialized by the boot reconcile step, so tests trigger it explicitly.
    reconcile_collector_nodes()
    return Collector.objects.get(collector_registry=f"{scope}:{key}")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestHappyPath:
    def test_run_succeeds_marks_job_successful(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert job.started_at is not None
        assert job.finished_at is not None
        # HappyCollector does not set self.summary, so the task body writes
        # an empty string on success.
        assert job.summary == ""

    def test_run_receives_correct_config(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        assert HappyCollector.runs == [str(job.entity_id)]

    def test_has_job_edge_created(self, isolate_collector_registry):
        from tap_grid.models import Edge

        col = _register_and_fetch("happy", HappyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)

        edges = Edge.objects.filter(
            from_entity=col.entity,
            to_entity=job.entity,
            edge_type="HAS_COLLECTION_JOB",
        )
        assert edges.count() == 1


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestFailurePath:
    """The Django immediate backend captures task exceptions on the TaskResult
    instead of re-raising to the caller (see
    django/tasks/backends/immediate.py). `run_collection` therefore returns
    normally even when the underlying collector raises; the failure surfaces
    via CollectionJob.status and summary."""

    def test_run_raises_marks_job_failed(self, isolate_collector_registry):
        col = _register_and_fetch("boom", BoomCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        # BoomCollector raises without calling record_error or setting
        # self.summary, so the task body falls back to the exception message.
        assert "boom from BoomCollector" in job.summary
        assert job.finished_at is not None

    def test_unregistered_collector_marks_job_failed(self, isolate_collector_registry):
        # Special case: a Collector node whose runner is NOT registered (the
        # "uninstalled-plugin" scenario). Under the phase-1 gate this now
        # fails via the self-test service entry point (RUNNER_UNAVAILABLE),
        # not via a phase-2 get_collector raise — so the operator gets a
        # readiness reason, not a stack-trace class name. We can't use
        # _register_and_fetch because it would register the runner too.
        from tap_grid.services import _create_node_internal_for_test

        result = _create_node_internal_for_test(
            "collector",
            {
                "name": "Never Registered",
                "description": "",
                "collector_registry": "tap_cares.tests.fakes:never-registered",
            },
        )
        assert result.success, result.errors
        col = Collector.objects.get(entity_id=result.entity_id)
        job = run_collection(col)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        # Phase-1 standard failure mode: summary is the self-test summary —
        # now loud + self-diagnosing (names the likely stale-supervisor cause
        # and the one-line fix) rather than a bare "not registered". Assert
        # the actionable behavior, not the exact prose.
        assert "not registered" in job.summary
        assert "scripts/dc restart web" in job.summary
        assert "req-tap-cares-task-backend-deployment-3" in job.summary
        # The structured readiness result is persisted on the job.
        assert job.self_test["status"] == "error"
        assert job.self_test["runnable"] is False
        assert job.self_test["checks"][0]["code"] == "RUNNER_UNAVAILABLE"
        assert job.self_test["checked_at"]

    def test_summary_capped_at_2048(self, isolate_collector_registry):
        from tap_cares.collectors import CollectorBase

        class LongBoom(CollectorBase):
            def run(self) -> None:
                raise RuntimeError("X" * 5000)

        col = _register_and_fetch("long", LongBoom, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        assert len(job.summary) <= 2048


# ---------------------------------------------------------------------------
# task_result_id propagation
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestTaskResultIdPropagation:
    def test_task_result_id_populated(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        assert job.task_result_id != ""
        assert len(job.task_result_id) <= 128


# ---------------------------------------------------------------------------
# Lifecycle timestamps
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestLifecycleTimestamps:
    def test_enqueued_at_set_before_task(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        assert job.enqueued_at is not None

    def test_started_at_before_finished_at(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        job.refresh_from_db()
        assert job.started_at is not None and job.finished_at is not None
        assert job.started_at <= job.finished_at


# ---------------------------------------------------------------------------
# JSON-safe task args (req-tap-cares-collector-task-execution-3)
# ---------------------------------------------------------------------------


class TestTaskInputContract:
    def test_collector_config_is_two_uuids(self):
        from uuid import uuid4

        cfg = CollectorConfig(collector_entity_id=uuid4(), collection_job_entity_id=uuid4())
        # Must be reducible to JSON-safe data.
        import dataclasses

        as_dict = dataclasses.asdict(cfg)
        assert set(as_dict.keys()) == {"collector_entity_id", "collection_job_entity_id"}


# ---------------------------------------------------------------------------
# Phase-1 self-test gate — req-tap-cares-collector-self-test-{10,16}
# ---------------------------------------------------------------------------


from tap_cares.collectors import CollectorBase  # noqa: E402
from tap_cares.collectors.readiness import (  # noqa: E402
    CollectorReadinessStatus,
    CollectorSelfTestResult,
    check_fail,
)
from tap_cares.models import CollectionJobRunMode  # noqa: E402


class _RunCountingCollector(CollectorBase):
    """Tracks whether run() was invoked, to prove phase gating."""

    run_calls: list[str] = []

    def run(self) -> None:
        type(self).run_calls.append(str(self.config.collection_job_entity_id))


class HappySelfTestCollector(_RunCountingCollector):
    """Default self_test (ready); run() succeeds."""


class NotReadyCollector(_RunCountingCollector):
    """A collector whose self-test reports a non-runnable status."""

    @classmethod
    def self_test(cls) -> CollectorSelfTestResult:
        return CollectorSelfTestResult.from_checks(
            [
                check_fail(
                    "FAKE_MISCONFIGURED",
                    "Fake collector is deliberately misconfigured for this test.",
                    readiness_status=CollectorReadinessStatus.MISCONFIGURED,
                )
            ],
            summary="Fake collector is misconfigured.",
        )


@pytest.fixture(autouse=True)
def _reset_run_counter():
    _RunCountingCollector.run_calls.clear()
    yield
    _RunCountingCollector.run_calls.clear()


@pytest.mark.django_db(transaction=True)
class TestPhaseOneGate:
    def test_full_run_persists_self_test(self, isolate_collector_registry):
        col = _register_and_fetch("happy-st", HappySelfTestCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert job.run_mode == CollectionJobRunMode.FULL
        # Phase-1 self_test rides on the successful terminal patch.
        assert job.self_test["status"] == "ready"
        assert job.self_test["runnable"] is True
        assert job.self_test["checked_at"]
        assert job.self_test["checks"][0]["code"] == "RUNNER_REGISTERED"
        assert _RunCountingCollector.run_calls == [str(job.entity_id)]

    def test_self_test_only_passes_without_collecting(self, isolate_collector_registry):
        col = _register_and_fetch("happy-sto", HappySelfTestCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col, run_mode=CollectionJobRunMode.SELF_TEST_ONLY)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert job.run_mode == CollectionJobRunMode.SELF_TEST_ONLY
        assert job.summary == "Self-test passed; no collection performed."
        assert job.self_test["status"] == "ready"
        # run() must NOT have been called — phase 1 only.
        assert _RunCountingCollector.run_calls == []

    def test_non_runnable_self_test_fails_before_phase_two(self, isolate_collector_registry):
        col = _register_and_fetch("not-ready", NotReadyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col)
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        # Standard failure mode: summary is the self-test summary.
        assert job.summary == "Fake collector is misconfigured."
        assert job.self_test["status"] == "misconfigured"
        assert job.self_test["runnable"] is False
        assert job.self_test["checks"][0]["code"] == "FAKE_MISCONFIGURED"
        # No phase-2 work, no partial collection.
        assert _RunCountingCollector.run_calls == []

    def test_self_test_only_still_fails_when_not_runnable(self, isolate_collector_registry):
        col = _register_and_fetch("not-ready-sto", NotReadyCollector, scope="tap_cares.tests.fakes")
        job = run_collection(col, run_mode=CollectionJobRunMode.SELF_TEST_ONLY)
        job.refresh_from_db()
        # A self_test_only job that is not runnable still fails — the run mode
        # only changes what happens on a *passing* phase 1.
        assert job.status == CollectionJobStatus.FAILED
        assert job.self_test["runnable"] is False
        assert _RunCountingCollector.run_calls == []


# ---------------------------------------------------------------------------
# Transactional integrity — req-tap-cares-task-backend-transactional-integrity
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestTransactionalIntegrity:
    """Positively assert the `transaction.on_commit` enqueue deferral.

    `req-tap-cares-task-backend-transactional-integrity-{1,3}` only claim to
    be "verified by the existing test suite continuing to pass" — i.e. by the
    *absence* of breakage. That is verification-by-nothing: deleting the
    `transaction.on_commit(...)` wrap in `run_collection` would leave every
    other test green (the happy-path tests pass because they commit, not
    because the wrap is correct).

    This test gives the requirement teeth. With the wrap intact, calling
    `run_collection` inside an outer `transaction.atomic()` must NOT execute
    the collector until that block commits — under `ImmediateBackend` the
    collector runs synchronously at `.enqueue()` time, so "did it run yet" is
    directly observable via `HappyCollector.runs` and `job.status`.

    Regression behavior: if the wrap is removed, `.enqueue()` fires inside the
    atomic block and the collector runs synchronously *before* commit, so the
    in-block `runs == []` / status-READY assertions fail. The transactional
    hazard this guards (a Steady Queue worker on another connection seeing a
    task row before the CollectionJob row commits) is production-only and
    otherwise has no automated guard at all.
    """

    def test_enqueue_is_deferred_until_outer_commit(self, isolate_collector_registry):
        from django.db import transaction

        col = _register_and_fetch("happy-txn", HappyCollector, scope="tap_cares.tests.fakes")

        with transaction.atomic():
            job = run_collection(col)
            # Inside the still-open outer transaction the on_commit callback
            # has NOT fired, so the enqueue is deferred and the collector has
            # not run. (Without the wrap, ImmediateBackend would have run it
            # synchronously here and these assertions would fail.)
            assert HappyCollector.runs == []
            assert job.status == CollectionJobStatus.READY
            assert job.started_at is None

        # The atomic block committed: on_commit fired -> enqueue -> the
        # ImmediateBackend ran the collector synchronously to completion.
        job.refresh_from_db()
        assert HappyCollector.runs == [str(job.entity_id)]
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert job.started_at is not None and job.finished_at is not None
