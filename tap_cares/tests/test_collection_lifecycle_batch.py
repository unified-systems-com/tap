"""One collection run, one batch for its own lifecycle — and it gets sealed.

Covers req-tap-cares-collector-run-collection-10..13
(tap_cares/specs/spec-tap-cares-collector.md), the collector half of the
one-unit-of-work-one-batch fix whose scheduler half is
req-tap-cares-scheduler-trigger-provenance-5.

Before this, one `run_collection(...)` left four auto-created batches behind —
the `CollectionJob` node, its `HAS_COLLECTION_JOB` edge, and the status
transitions — each minted by the service layer because the write arrived with
no batch of its own, and none of them ever closed. `status='open'` therefore
stopped meaning "in flight". These tests assert the three things that make the
fix real rather than merely present: the count is one, the one is sealed, and
the GRIFT batch the collector imports is still its own.

Runs under ImmediateBackend (tap/settings.py), so `.enqueue()` executes the
task synchronously and the run is complete by the time `run_collection`
returns — including the worker-side half of the lifecycle, which is the half
that has to be threaded across the task boundary.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tap_cares.collectors import CollectorBase
from tap_cares.models import CollectionJob, CollectionJobStatus, Collector
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import LIFECYCLE_BATCH_SOURCE, run_collection
from tap_cares.tests.fakes import BoomCollector, HappyCollector
from tap_grid.batch import AUTO_BATCH_SOURCE
from tap_grid.models import Batch, BatchStatus

SCOPE = "tap_cares.tests.test_collection_lifecycle_batch"


def _register_and_fetch(key: str, cls) -> Collector:
    register_collector(
        key=key,
        cls=cls,
        scope=SCOPE,
        name=f"Lifecycle-batch fixture {key}",
        description="Fixture collector for the one-run-one-lifecycle-batch tests.",
    )
    reconcile_collector_nodes()
    collector: Collector = Collector.objects.get(collector_registry=f"{SCOPE}:{key}")
    return collector


def _batches_created_by(fn) -> list[Any]:
    """Every Batch row that appeared while `fn` ran, newest last."""
    before = set(Batch.objects.values_list("entity_id", flat=True))
    fn()
    return list(Batch.objects.exclude(entity_id__in=before).order_by("started_at", "entity_id"))


class _GriftCollector(CollectorBase):
    """Imports one real GRIFT batch, so the separation claim is tested, not assumed."""

    def run(self) -> None:
        self.submit_grift(
            {
                "metadata": {"grift_version": "0"},
                "_reserved": {},
                "batches": [
                    {
                        "batch_entity": {
                            "entity_id": str(uuid.uuid4()),
                            "entity_type": "batch",
                            "name": "Imported data",
                            "dimensions": {},
                        },
                        "batch_node": {
                            "name": "Imported data",
                            "description": "",
                            "description_json": None,
                            "source": "lifecycle-batch-test-source",
                            "metadata": {},
                        },
                        "nodes": [],
                        "edges": [],
                    }
                ],
            }
        )


@pytest.mark.django_db(transaction=True)
class TestOneRunOneLifecycleBatch:
    def test_one_run_opens_exactly_one_lifecycle_batch(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector)

        created = _batches_created_by(lambda: run_collection(col))

        lifecycle = [b for b in created if b.source == LIFECYCLE_BATCH_SOURCE]
        assert len(lifecycle) == 1, [(b.source, b.name) for b in created]

    def test_the_lifecycle_batch_is_closed_when_the_job_reaches_terminal(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector)

        job = run_collection(col)

        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        assert batch.status == BatchStatus.CLOSED
        assert batch.closed_at is not None

    def test_the_lifecycle_batch_is_named_and_attributed(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector)

        run_collection(col)

        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        assert batch.name.startswith("Collection job lifecycle:")
        assert col.name in batch.name
        assert batch.entity.name == batch.name

    def test_the_run_leaves_no_auto_created_batches_behind(self, isolate_collector_registry):
        """The defect in one assertion: four `tap_grid.services.write_batch` rows, all open."""
        col = _register_and_fetch("happy", HappyCollector)

        created = _batches_created_by(lambda: run_collection(col))

        assert [b for b in created if b.source == AUTO_BATCH_SOURCE] == []

    def test_no_batch_from_this_run_is_left_open(self, isolate_collector_registry):
        col = _register_and_fetch("happy", HappyCollector)

        created = _batches_created_by(lambda: run_collection(col))

        assert [b.name for b in created if b.status == BatchStatus.OPEN] == []

    def test_both_task_boundary_halves_ride_the_same_batch(self, isolate_collector_registry):
        """The kickoff writes and the worker's status writes are one batch, not two.

        This is the claim the task-payload threading exists to make: the node and
        edge are written by `run_collection`, the RUNNING and terminal patches by
        the task body on the far side of `.enqueue()`. If the batch id did not
        cross that boundary, the worker's writes would mint their own.
        """
        from tap_grid.batch import get_batch_events

        col = _register_and_fetch("happy", HappyCollector)
        job = run_collection(col)

        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        touched = {str(e.entity_id) for e in get_batch_events(str(batch.entity_id))}
        # The CollectionJob node was created by run_collection and patched twice
        # by the worker; every one of those events is in this one batch.
        assert str(job.entity_id) in touched
        events_on_job = [e for e in get_batch_events(str(batch.entity_id)) if str(e.entity_id) == str(job.entity_id)]
        assert len(events_on_job) >= 2


@pytest.mark.django_db(transaction=True)
class TestFailedRun:
    def test_a_failed_run_fails_its_lifecycle_batch(self, isolate_collector_registry):
        col = _register_and_fetch("boom", BoomCollector)

        job = run_collection(col)

        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED
        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        assert batch.status == BatchStatus.FAILED
        assert batch.error_message == job.summary

    def test_a_failed_run_still_leaves_exactly_one_lifecycle_batch(self, isolate_collector_registry):
        col = _register_and_fetch("boom", BoomCollector)

        created = _batches_created_by(lambda: run_collection(col))

        assert len([b for b in created if b.source == LIFECYCLE_BATCH_SOURCE]) == 1
        assert [b for b in created if b.source == AUTO_BATCH_SOURCE] == []

    def test_a_kickoff_failure_does_not_strand_an_empty_open_batch(self, isolate_collector_registry, monkeypatch):
        """A batch opened for writes that never came is failed, not left `open`."""
        col = _register_and_fetch("happy-kickoff", HappyCollector)

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("edge write exploded")

        monkeypatch.setattr("tap_cares.services.create_edge", _boom)

        with pytest.raises(RuntimeError):
            run_collection(col)

        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        assert batch.status == BatchStatus.FAILED
        assert "edge write exploded" in batch.error_message


@pytest.mark.django_db(transaction=True)
class TestGriftBatchStaysSeparate:
    def test_the_imported_batch_is_its_own_named_closed_batch(self, isolate_collector_registry):
        col = _register_and_fetch("grifter", _GriftCollector)

        created = _batches_created_by(lambda: run_collection(col))

        lifecycle = [b for b in created if b.source == LIFECYCLE_BATCH_SOURCE]
        imported = [b for b in created if b.source == "lifecycle-batch-test-source"]
        assert len(lifecycle) == 1
        assert len(imported) == 1
        assert imported[0].entity_id != lifecycle[0].entity_id
        assert imported[0].status == BatchStatus.CLOSED
        assert lifecycle[0].status == BatchStatus.CLOSED
        # Nothing else: no service-layer scaffolding batches either side of it.
        assert [b for b in created if b.source == AUTO_BATCH_SOURCE] == []


def _job_in_its_own_lifecycle_batch(status: str) -> tuple[Any, str]:
    """A lifecycle batch and a job whose spine row records that batch, at `status`.

    The binding is the whole point: a job created OUTSIDE the batch fails
    `_is_lifecycle_batch_of`, and every assertion built on it would then pass
    through the wrong guard — green for a reason the test does not name. The
    premise is asserted here rather than assumed.
    """
    from tap_grid.batch import create_batch
    from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
    from tap_grid.services import _create_node_internal

    batch = create_batch(name="Collection job lifecycle: fixture", source=LIFECYCLE_BATCH_SOURCE)
    prior = get_caller_context()
    set_caller_context(CallerContext(user=prior.user if prior else None, batch_id=str(batch.entity_id)))
    try:
        result = _create_node_internal(
            "collection_job",
            {"name": f"Fixture run ({status})", "status": status, "run_mode": "full"},
        )
    finally:
        set_caller_context(prior)
    assert result.success, result.errors
    job = CollectionJob.objects.get(entity_id=result.entity_id)
    assert str(job.batch_id) == str(batch.entity_id)
    return batch, str(result.entity_id)


@pytest.mark.django_db(transaction=True)
class TestNonTerminalJobKeepsItsBatchOpen:
    """req-tap-cares-collector-run-collection-12 — the deliberate non-behavior.

    A worker pruned mid-run never writes terminal state, so the job stays
    `RUNNING`. Sealing its batch anyway would assert the run is over on no
    evidence — the presence-is-not-correctness shape. The batch stays `open`,
    matching the job, and unified-systems-com/tap#471's reconciliation resolves
    both from the same authority. This is what stops a future well-meaning timer
    from being added here instead.
    """

    def test_a_running_job_leaves_its_batch_open(self, isolate_collector_registry):
        from tap_cares.services import _seal_lifecycle_batch

        batch, job_entity_id = _job_in_its_own_lifecycle_batch(CollectionJobStatus.RUNNING.value)

        _seal_lifecycle_batch(str(batch.entity_id), job_entity_id)

        batch.refresh_from_db()
        assert batch.status == BatchStatus.OPEN

    def test_the_same_fixture_at_a_terminal_status_does_seal(self, isolate_collector_registry):
        """Positive control. Without it, a batch left `open` because the BINDING was
        refused reads exactly like one left open because the status was not terminal —
        and the terminal-state guard could be deleted with this suite still green."""
        from tap_cares.services import _seal_lifecycle_batch

        batch, job_entity_id = _job_in_its_own_lifecycle_batch(CollectionJobStatus.SUCCESSFUL.value)

        _seal_lifecycle_batch(str(batch.entity_id), job_entity_id)

        batch.refresh_from_db()
        assert batch.status == BatchStatus.CLOSED


@pytest.mark.django_db(transaction=True)
class TestDeferredKickoffFailure:
    """req-tap-cares-collector-run-collection-13, the half a synchronous test misses.

    When a caller wraps `run_collection` in its own `transaction.atomic()`, the
    enqueue is deferred to `on_commit` and runs AFTER `run_collection` has
    returned — so the in-function failure handler is no longer on the stack. An
    enqueue that raises there would strand a committed, empty, `open` batch with
    no task ever coming: the exact state this change exists to eliminate.
    """

    def test_an_enqueue_that_fails_after_commit_still_fails_the_batch(self, isolate_collector_registry, monkeypatch):
        from django.db import transaction

        col = _register_and_fetch("happy-deferred", HappyCollector)

        class _BrokenQueue:
            """A task whose enqueue raises — a Task is a frozen dataclass, so stand in for it."""

            def enqueue(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("queue is down")

        monkeypatch.setattr("tap_cares.services.run_collector", _BrokenQueue())

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                run_collection(col)

        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        assert batch.status == BatchStatus.FAILED
        assert "queue is down" in batch.error_message

    def test_a_task_id_bookkeeping_failure_does_not_fail_a_live_run(self, isolate_collector_registry, monkeypatch):
        """Only the ENQUEUE failing may fail the batch — not what happens after it.

        Past a successful enqueue the task is accepted and the run is live, so
        the batch must stay open for the worker to seal. Failing it on a
        `task_result_id` write would hand a SUCCESSFUL job a permanently FAILED
        batch — the disagreement this whole change exists to prevent — and the
        seal could not correct it, because a non-OPEN batch is left alone.
        `task_result_id` is correlation metadata nothing reads (the sole-writer
        invariant), so its failure is logged and goes no further.
        """
        col = _register_and_fetch("happy-taskid", HappyCollector)

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("bookkeeping write failed")

        # Only the enqueue-side task_result_id patch resolves through this name;
        # the task body imports `_patch_node_internal` into tap_cares.tasks.
        monkeypatch.setattr("tap_cares.services._patch_node_internal", _boom)

        job = run_collection(col)

        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL
        batch = Batch.objects.get(source=LIFECYCLE_BATCH_SOURCE)
        assert batch.status == BatchStatus.CLOSED


@pytest.mark.django_db(transaction=True)
class TestSealRefusesAForeignBatch:
    """req-tap-cares-collector-run-collection-16.

    The batch id reaches the seal in a task payload, alongside a separately
    supplied job id. Nothing in that pairing is self-evident, so the seal derives
    two facts before it writes: the batch's `source` says the collector runtime
    produced it, and the job's own spine row says its writes rode that batch.
    Without this, a wrong third argument — a future caller, a bug, tap#471's
    reconciler — closes somebody else's open batch under the collector actor.
    """

    def test_a_batch_the_collector_did_not_produce_is_refused(self, isolate_collector_registry):
        from tap_cares.services import _seal_lifecycle_batch
        from tap_grid.batch import create_batch

        _, job_entity_id = _job_in_its_own_lifecycle_batch(CollectionJobStatus.SUCCESSFUL.value)
        foreign = create_batch(name="Somebody else's import", source="some_plugin.grift")

        _seal_lifecycle_batch(str(foreign.entity_id), job_entity_id)

        foreign.refresh_from_db()
        assert foreign.status == BatchStatus.OPEN

    def test_a_lifecycle_batch_belonging_to_another_job_is_refused(self, isolate_collector_registry):
        from tap_cares.services import _seal_lifecycle_batch
        from tap_grid.batch import create_batch

        _, job_entity_id = _job_in_its_own_lifecycle_batch(CollectionJobStatus.SUCCESSFUL.value)
        other = create_batch(name="Collection job lifecycle: another run", source=LIFECYCLE_BATCH_SOURCE)

        _seal_lifecycle_batch(str(other.entity_id), job_entity_id)

        other.refresh_from_db()
        assert other.status == BatchStatus.OPEN


@pytest.mark.django_db(transaction=True)
class TestTheWorkerRefusesToWriteIntoAForeignBatch:
    """req-tap-cares-collector-run-collection-16, the half the seal cannot cover.

    The seal refuses to CLOSE a foreign batch — but by then the run's status
    patches and `PRODUCED_BATCH` edges would already have been written into it,
    and a closed batch is not an append barrier, so refusing late does not take
    them back. The worker therefore verifies the same binding BEFORE
    `acting_as(..., batch_id=...)` scopes anything, and runs unscoped when it
    does not hold: a bad third argument must not stop collection, only misfile it.
    """

    def test_a_payload_naming_a_foreign_batch_writes_nothing_into_it(self, isolate_collector_registry):
        from tap_cares.tasks import run_collector
        from tap_grid.batch import create_batch, get_batch_events

        col = _register_and_fetch("happy-foreign", HappyCollector)
        job = run_collection(col)
        foreign = create_batch(name="Somebody else's import", source="some_plugin.grift")

        # The same job, re-run pointed at a batch that is not its own — the shape
        # a wrong third argument produces.
        run_collector.enqueue(str(col.entity_id), str(job.entity_id), str(foreign.entity_id))

        assert get_batch_events(str(foreign.entity_id)) == []
        foreign.refresh_from_db()
        assert foreign.status == BatchStatus.OPEN
