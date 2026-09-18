"""A collector's surface statements reach the run's lifecycle batch (req-grid-reconcile-evidence).

End to end through `run_collection`: the collector accumulates `record_surface(...)` calls
next to its GRIFT submissions; the task body records the statement on the lifecycle batch
before the terminal patch; `applied` is derived from the produced batch's committed status.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.utils import timezone

from tap_cares.collectors import CollectorBase
from tap_cares.models import CollectionJobStatus, Collector
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import LIFECYCLE_BATCH_SOURCE, run_collection
from tap_grid.completeness import completeness_of
from tap_grid.models import Batch


def _doc() -> dict[str, Any]:
    from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _character_node, _minimal_doc

    return _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_character_node(str(uuid.uuid4()))])])


class SurfaceCollector(CollectorBase):
    """Submits one GRIFT batch and says what it can about the surface it came from."""

    def run(self) -> None:
        started = timezone.now().isoformat()
        self.submit_grift(_doc())
        self.record_surface(
            relation="repository.workflows",
            subject="repo:fixture",
            interval={"first": started, "last": timezone.now().isoformat()},
            scope_authorized=True,
            enumeration_complete=True,
            source_consistent="unknown",
            admitted=True,
            applied_batches=[batch_id for batch_id, _ in self._produced_batches],
            reasons={"source_consistent": "fixture source makes no snapshot promise"},
        )
        self.summary = "one surface, one batch"


class SurfaceThenBoomCollector(SurfaceCollector):
    """Records its surface, then fails: the statement must still be recorded."""

    def run(self) -> None:
        super().run()
        raise RuntimeError("boom after the surface was recorded")


class NoSurfacesCollector(CollectorBase):
    """Reads nothing and says so: a statement with zero surfaces, not no statement."""

    def run(self) -> None:
        self.declare_no_surfaces()


class SilentCollector(CollectorBase):
    """Never mentions completeness: no statement at all."""

    def run(self) -> None:
        return None


class ForeignBatchCollector(CollectorBase):
    """Cites a committed batch this run did not produce: refused, not applied."""

    def run(self) -> None:
        from tap_grid.batch import close_batch, create_batch

        foreign = close_batch(create_batch(source="somebody.else"))
        self.record_surface(
            relation="repository.workflows",
            subject="repo:fixture",
            interval={"first": timezone.now().isoformat(), "last": timezone.now().isoformat()},
            scope_authorized=True,
            enumeration_complete=True,
            source_consistent="unknown",
            admitted=True,
            applied_batches=[str(foreign.entity_id)],
            reasons={"source_consistent": "fixture"},
        )


class BadSurfaceCollector(CollectorBase):
    """Authors a derived field: the recorder refuses, the run still succeeds, nothing recorded."""

    def run(self) -> None:
        self.record_surface(relation="x", subject="y", applied=True)


def _register(key: str, cls: type[CollectorBase]) -> Collector:
    register_collector(
        key=key, cls=cls, scope="tap_cares.tests.completeness", name=f"{key} fixture", description="fixture"
    )
    reconcile_collector_nodes()
    collector = Collector.objects.get(collector_registry=f"tap_cares.tests.completeness:{key}")
    assert isinstance(collector, Collector)
    return collector


def _lifecycle_batch(job: Any) -> Batch:
    from tap_grid.models import Edge

    edge = Edge.objects.filter(edge_type="HAS_COLLECTION_JOB", to_entity_id=job.entity_id).first()
    assert edge is not None
    batch = Batch.objects.filter(source=LIFECYCLE_BATCH_SOURCE, entity_id=edge.batch_id).first()
    assert isinstance(batch, Batch), "the job's HAS_COLLECTION_JOB edge rides its lifecycle batch"
    return batch


@pytest.mark.django_db(transaction=True)
class TestSurfaceStatementsReachTheRun:
    @pytest.mark.spec("req-grid-reconcile-evidence-1")
    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_a_successful_run_records_its_surfaces_with_applied_derived(self, isolate_collector_registry: Any) -> None:
        job = run_collection(_register("surface", SurfaceCollector))
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL.value
        statement = completeness_of(_lifecycle_batch(job))
        assert statement is not None
        [s] = statement["surfaces"]
        assert s["relation"] == "repository.workflows"
        assert s["applied"] is True, "the produced GRIFT batch committed"
        assert s["reconcilable"] is True

    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_a_failed_run_still_records_what_it_read(self, isolate_collector_registry: Any) -> None:
        job = run_collection(_register("boom", SurfaceThenBoomCollector))
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.FAILED.value
        statement = completeness_of(_lifecycle_batch(job))
        assert statement is not None
        assert statement["surfaces"][0]["applied"] is True, "the GRIFT batch committed before the collector failed"

    def test_zero_surfaces_and_no_statement_are_distinct(self, isolate_collector_registry: Any) -> None:
        """Codex on PR# 577 - tap: a run that touched no surface can say so."""
        said_so = run_collection(_register("nosurfaces", NoSurfacesCollector))
        silent = run_collection(_register("silent", SilentCollector))
        said_so.refresh_from_db()
        silent.refresh_from_db()
        assert completeness_of(_lifecycle_batch(said_so)) == {"recorded_at": completeness_of(_lifecycle_batch(said_so))["recorded_at"], "surfaces": []}  # type: ignore[index]
        assert completeness_of(_lifecycle_batch(silent)) is None

    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_a_foreign_batch_is_refused_not_applied(self, isolate_collector_registry: Any, caplog: Any) -> None:
        """Codex on PR# 577 - tap: applied_batches is bound to the batches this run produced."""
        job = run_collection(_register("foreign", ForeignBatchCollector))
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL.value
        assert completeness_of(_lifecycle_batch(job)) is None
        assert any("[23f6]" in rec.message and "batch_not_produced" in rec.message for rec in caplog.records)

    def test_a_refused_statement_does_not_fail_the_run(self, isolate_collector_registry: Any, caplog: Any) -> None:
        job = run_collection(_register("bad", BadSurfaceCollector))
        job.refresh_from_db()
        assert job.status == CollectionJobStatus.SUCCESSFUL.value
        assert completeness_of(_lifecycle_batch(job)) is None
        assert any("[23f6]" in rec.message for rec in caplog.records), "the refusal is logged against the run"
