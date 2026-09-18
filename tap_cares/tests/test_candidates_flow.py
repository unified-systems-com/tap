"""A run's candidate record reaches its lifecycle batch (req-grid-reconcile-candidates).

End to end through `run_collection`: the collector submits what it saw as GRIFT and records
the parent's surface with its relation mapped to the grid edge type; the task body derives
the candidates from that statement and the run's own produced batches, compares scope with
the collector's previous successful run, and records the result beside the statement —
with authority off, so the fixture's absent child is named and never retired.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest
from django.utils import timezone

from tap_cares.collectors import CollectorBase
from tap_cares.models import CollectionJobStatus, Collector
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import run_collection
from tap_cares.tests.test_completeness_flow import _lifecycle_batch
from tap_grid.batch import batch_summary, produced_batches
from tap_grid.candidates import ABSENT, candidates_of
from tap_grid.models import Entity

SOURCE = "grid_fixtures__constrained_source"
TARGET = "grid_fixtures__constrained_target"
CONTAINS = "CONSTRAINED_LINK__grid_fixtures"


@pytest.fixture(autouse=True)
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.grid_fixtures.models import ConstrainedSource

    monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (CONTAINS,), raising=False)


def _node(entity_id: str, entity_type: str, name: str) -> dict[str, Any]:
    return {
        "entity": {"entity_id": entity_id, "entity_type": entity_type, "name": name, "dimensions": {}},
        "node": {"name": name, "description": ""},
    }


def _edge(edge_id: str, from_id: str, to_id: str) -> dict[str, Any]:
    return {
        "entity": {"entity_id": edge_id, "entity_type": "edge", "dimensions": {}},
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": CONTAINS, "properties": {}},
    }


class DescentCollector(CollectorBase):
    """Lists one parent's children. Which children it sees is set on the class between runs."""

    PARENT: ClassVar[str] = str(uuid.uuid4())
    CHILDREN: ClassVar[dict[str, str]] = {name: str(uuid.uuid4()) for name in ("c1", "c2", "c3")}
    EDGES: ClassVar[dict[str, str]] = {name: str(uuid.uuid4()) for name in ("c1", "c2", "c3")}
    SEEN: ClassVar[tuple[str, ...]] = ("c1", "c2", "c3")

    def run(self) -> None:
        from tap_grid.tests.test_grift import _batch_container, _minimal_doc

        started = timezone.now().isoformat()
        nodes = [_node(self.PARENT, SOURCE, "P")] + [_node(self.CHILDREN[n], TARGET, n) for n in self.SEEN]
        edges = [_edge(self.EDGES[n], self.PARENT, self.CHILDREN[n]) for n in self.SEEN]
        self.submit_grift(_minimal_doc([_batch_container(str(uuid.uuid4()), nodes=nodes, edges=edges)]))
        self.record_surface(
            relation="source.targets",
            edge_type=CONTAINS,
            subject=self.PARENT,
            interval={"first": started, "last": timezone.now().isoformat()},
            scope_authorized=True,
            enumeration_complete=True,
            source_consistent="unknown",
            admitted=True,
            applied_batches=[batch_id for batch_id, _ in self._produced_batches],
            reasons={"source_consistent": "fixture source makes no snapshot promise"},
        )


class LocatorSubjectCollector(CollectorBase):
    """Names its subject as a source locator: the statement is recorded, the derivation skips it."""

    def run(self) -> None:
        now = timezone.now().isoformat()
        self.record_surface(
            relation="repository.workflows",
            subject="repo:fixture",
            interval={"first": now, "last": now},
            scope_authorized=True,
            enumeration_complete=True,
            source_consistent="unknown",
            admitted=True,
            applied_batches=[],
            reasons={"source_consistent": "fixture", "applied": "nothing written"},
        )


class SilentCollector(CollectorBase):
    def run(self) -> None:
        return None


def _register(key: str, cls: type[CollectorBase]) -> Collector:
    register_collector(
        key=key, cls=cls, scope="tap_cares.tests.candidates", name=f"{key} fixture", description="fixture"
    )
    reconcile_collector_nodes()
    collector = Collector.objects.get(collector_registry=f"tap_cares.tests.candidates:{key}")
    assert isinstance(collector, Collector)
    return collector


def _run(collector: Collector) -> Any:
    job = run_collection(collector)
    job.refresh_from_db()
    assert job.status == CollectionJobStatus.SUCCESSFUL.value, job.summary
    return job


@pytest.mark.django_db(transaction=True)
class TestCandidatesReachTheRun:
    @pytest.mark.spec("req-grid-reconcile-candidates-1")
    @pytest.mark.spec("req-grid-reconcile-candidates-4")
    def test_the_second_run_names_the_child_the_first_saw_and_it_did_not(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        collector = _register("descent", DescentCollector)

        monkeypatch.setattr(DescentCollector, "SEEN", ("c1", "c2", "c3"))
        first = _run(collector)
        first_record = candidates_of(_lifecycle_batch(first))
        assert first_record is not None
        [entry] = first_record["surfaces"]
        assert entry["outcome"] == "derived" and entry["candidates"] == []
        assert (entry["children"], entry["observed"]) == (3, 3)
        assert first_record["previous"] is None, "no earlier run: withdrawal not observable"

        monkeypatch.setattr(DescentCollector, "SEEN", ("c1", "c2"))
        second = _run(collector)
        lifecycle = _lifecycle_batch(second)
        record = candidates_of(lifecycle)
        assert record is not None
        [entry] = record["surfaces"]
        assert entry["outcome"] == "derived"
        assert [c["entity_id"] for c in entry["candidates"]] == [DescentCollector.CHILDREN["c3"]]
        assert entry["candidates"][0] == {
            "entity_id": DescentCollector.CHILDREN["c3"],
            "entity_type": TARGET,
            "reason": ABSENT,
        }
        assert record["observed_batches"] == produced_batches(second.entity_id)["imported"]
        assert record["previous"]["batch"] == str(_lifecycle_batch(first).entity_id)
        assert record["previous"]["compared"] is True
        assert record["previous"]["observed_batches"] == produced_batches(first.entity_id)["imported"]
        assert record["authority"] == "off"
        assert Entity.objects.get(pk=DescentCollector.CHILDREN["c3"]).deleted_at is None, "named, not retired"
        summary = batch_summary(lifecycle.entity_id, with_counts=False)
        assert summary is not None and summary["candidates"] == record

    def test_an_unresolved_subject_is_recorded_as_skipped(self, isolate_collector_registry: Any) -> None:
        job = _run(_register("locator", LocatorSubjectCollector))
        record = candidates_of(_lifecycle_batch(job))
        assert record is not None
        [entry] = record["surfaces"]
        assert entry["outcome"] == "skipped" and entry["reason"].startswith("subject_unresolved")

    def test_no_statement_means_no_record(self, isolate_collector_registry: Any) -> None:
        job = _run(_register("silent", SilentCollector))
        assert candidates_of(_lifecycle_batch(job)) is None
