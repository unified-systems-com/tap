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
from tap_cares.models import CollectionJobStatus, Collector
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


@pytest.mark.django_db
class TestNonTerminalJobKeepsItsBatchOpen:
    """req-tap-cares-collector-run-collection-12 — the deliberate non-behavior.

    A worker pruned mid-run never writes terminal state, so the job stays
    `RUNNING`. Sealing its batch anyway would assert the run is over on no
    evidence — the presence-is-not-correctness shape. The batch stays `open`,
    matching the job, and unified-systems-com/tap#471's reconciliation resolves
    both from the same authority. This test is what stops a future well-meaning
    timer from being added here instead.
    """

    def test_a_running_job_leaves_its_batch_open(self, isolate_collector_registry):
        from tap_cares.services import _seal_lifecycle_batch
        from tap_grid.batch import create_batch
        from tap_grid.services import _create_node_internal

        batch = create_batch(name="Collection job lifecycle: fixture", source=LIFECYCLE_BATCH_SOURCE)
        result = _create_node_internal(
            "collection_job",
            {
                "name": "Interrupted run",
                "status": CollectionJobStatus.RUNNING.value,
                "run_mode": "full",
            },
        )
        assert result.success, result.errors

        _seal_lifecycle_batch(str(batch.entity_id), str(result.entity_id))

        batch.refresh_from_db()
        assert batch.status == BatchStatus.OPEN
