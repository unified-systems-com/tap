"""PRODUCED_BATCH claims: one edge per (job, batch), and at most one job holds a batch as imported.

Spec: ``req-grid-edge-produced-batch-claims`` in ``tap_grid/specs/spec-grid-edge.md`` (Issue# 918 -
tap). End to end through ``run_collection``: each fixture collector submits GRIFT and the task body
links what it produced. A competing ``imported`` claim cannot arise from the importer alone (a
batch already present is skipped), so the conflict fixture adds one to its own accumulator, which
is the state the rule guards against.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, ClassVar

import pytest

from tap_cares.collectors import CollectorBase
from tap_cares.models import CollectionJob, CollectionJobStatus, Collector
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import run_collection
from tap_cares.tasks import _collapse_claims, _link_produced_batches
from tap_grid.batch import imported_by, produced_batches
from tap_grid.models import Edge

SPEC = {n: pytest.mark.spec(f"req-grid-edge-produced-batch-claims-{n}") for n in (2, 3, 4)}


def _document(batch_id: str) -> dict[str, Any]:
    from tap_grid.tests.test_grift import _batch_container, _minimal_doc

    node_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"produced-batch-claims/{batch_id}"))
    node = {
        "entity": {"entity_id": node_id, "entity_type": "grid_fixtures__node", "name": "n", "dimensions": {}},
        "node": {"name": "n", "description": ""},
    }
    return _minimal_doc([_batch_container(batch_id, nodes=[node])])


class SubmitsTwice(CollectorBase):
    """Submits one document twice in one run: imported, then skipped."""

    BATCH: ClassVar[str] = ""

    def run(self) -> None:
        self.submit_grift(_document(self.BATCH))
        self.submit_grift(_document(self.BATCH))


class SubmitsOnce(CollectorBase):
    BATCH: ClassVar[str] = ""

    def run(self) -> None:
        self.submit_grift(_document(self.BATCH))


class ClaimsAnothersBatch(CollectorBase):
    """Claims to have imported a batch another job already holds as imported."""

    BATCH: ClassVar[str] = ""
    FAIL: ClassVar[bool] = False

    def run(self) -> None:
        self._produced_batches.append((self.BATCH, "imported"))
        if self.FAIL:
            raise RuntimeError("fixture: the collector fails after its claims")


class ClaimsAMissingBatch(CollectorBase):
    """Reports a batch that does not exist, so its claim cannot become an edge."""

    def run(self) -> None:
        self._produced_batches.append((str(uuid.uuid4()), "skipped"))


class Silent(CollectorBase):
    def run(self) -> None:
        return None


def _register(key: str, cls: type[CollectorBase]) -> Collector:
    register_collector(key=key, cls=cls, scope="tap_cares.tests.claims", name=f"{key} fixture", description="fixture")
    reconcile_collector_nodes()
    collector = Collector.objects.get(collector_registry=f"tap_cares.tests.claims:{key}")
    assert isinstance(collector, Collector)
    return collector


def _run(collector: Collector, *, expect: str = CollectionJobStatus.SUCCESSFUL.value) -> CollectionJob:
    job = run_collection(collector)
    job.refresh_from_db()
    assert job.status == expect, job.summary
    return job


def _edges(job: CollectionJob, batch_id: str) -> list[Any]:
    return list(Edge.objects.filter(edge_type="PRODUCED_BATCH", from_entity_id=job.entity_id, to_entity_id=batch_id))


def _conflicts(job: CollectionJob) -> list[dict[str, Any]]:
    return [e for e in job.results["error"] if e["message_code"] == "PRODUCED_BATCH_CONFLICT"]


@SPEC[2]
@pytest.mark.parametrize(
    ("claims", "collapsed"),
    [
        ([("b", "imported"), ("b", "skipped")], {"b": "imported"}),
        ([("b", "skipped"), ("b", "imported")], {"b": "imported"}),
        ([("b", "skipped"), ("b", "skipped")], {"b": "skipped"}),
        ([("a", "skipped"), ("b", "imported"), ("a", "imported")], {"a": "imported", "b": "imported"}),
    ],
)
def test_repeat_claims_collapse_and_imported_wins(claims: list[tuple[str, str]], collapsed: dict[str, str]) -> None:
    result = _collapse_claims(claims)
    assert result == collapsed
    assert list(result) == list(collapsed), "first-seen order"


@pytest.mark.django_db(transaction=True)
class TestClaims:
    @SPEC[2]
    def test_a_batch_submitted_twice_in_one_run_is_one_imported_edge(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch = str(uuid.uuid4())
        monkeypatch.setattr(SubmitsTwice, "BATCH", batch)
        job = _run(_register("twice", SubmitsTwice))
        (edge,) = _edges(job, batch)
        assert edge.properties["disposition"] == "imported"
        assert produced_batches(job.entity_id) == {"imported": [batch], "skipped": []}

    @SPEC[3]
    def test_a_later_job_skipping_a_batch_it_did_not_produce_is_fine(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch = str(uuid.uuid4())
        monkeypatch.setattr(SubmitsOnce, "BATCH", batch)
        collector = _register("once", SubmitsOnce)
        first, later = _run(collector), _run(collector)
        assert produced_batches(first.entity_id) == {"imported": [batch], "skipped": []}
        assert produced_batches(later.entity_id) == {"imported": [], "skipped": [batch]}
        assert _conflicts(later) == []
        assert imported_by(batch) == [str(first.entity_id)]

    @SPEC[4]
    def test_a_second_imported_claim_is_refused_and_recorded_on_the_job(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch = str(uuid.uuid4())
        monkeypatch.setattr(SubmitsOnce, "BATCH", batch)
        monkeypatch.setattr(ClaimsAnothersBatch, "BATCH", batch)
        producer = _run(_register("producer", SubmitsOnce))
        claimant = _run(_register("claimant", ClaimsAnothersBatch))  # status unchanged: SUCCESSFUL
        (conflict,) = _conflicts(claimant)
        assert conflict["message_data"] == {"batch_entity_id": batch, "imported_by": [str(producer.entity_id)]}
        assert _edges(claimant, batch) == []
        assert imported_by(batch) == [str(producer.entity_id)]

    @SPEC[4]
    def test_a_failed_run_records_a_refused_claim_too(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch = str(uuid.uuid4())
        monkeypatch.setattr(SubmitsOnce, "BATCH", batch)
        monkeypatch.setattr(ClaimsAnothersBatch, "BATCH", batch)
        monkeypatch.setattr(ClaimsAnothersBatch, "FAIL", True)
        _run(_register("producer", SubmitsOnce))
        claimant = _run(_register("failing", ClaimsAnothersBatch), expect=CollectionJobStatus.FAILED.value)
        assert len(_conflicts(claimant)) == 1

    @SPEC[2]
    def test_linking_again_makes_no_second_edge_and_imported_upgrades_skipped(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
        from tap_grid.batch import create_batch

        batch = str(uuid.uuid4())
        monkeypatch.setattr(SubmitsOnce, "BATCH", batch)
        producer = _run(_register("producer", SubmitsOnce))
        other = str(uuid.uuid4())
        monkeypatch.setattr(SubmitsOnce, "BATCH", other)
        job = _run(_register("relinked", SubmitsOnce))
        # Outside a run there is no lifecycle batch to join, so the writes are labelled their own.
        with acting_as(
            get_builtin_actor(COLLECTOR), batch_name="relink fixture", batch_description="linking again, outside a run"
        ):
            assert _link_produced_batches(job, [(other, "imported")]) == []
            assert _link_produced_batches(job, [(batch, "skipped")]) == []
            assert _link_produced_batches(job, [(batch, "skipped")]) == []
            unclaimed = str(create_batch(name="unclaimed fixture", description="no job holds it").entity_id)
            assert _link_produced_batches(job, [(unclaimed, "skipped")]) == []
            assert _link_produced_batches(job, [(unclaimed, "imported")]) == []
        assert len(_edges(job, other)) == 1
        (skipped,) = _edges(job, batch)
        assert skipped.properties["disposition"] == "skipped"
        assert imported_by(batch) == [str(producer.entity_id)]
        (upgraded,) = _edges(job, unclaimed)
        assert upgraded.properties["disposition"] == "imported"

    @SPEC[4]
    def test_a_claim_that_cannot_be_linked_is_recorded_on_the_job(self, isolate_collector_registry: Any) -> None:
        job = _run(_register("missing", ClaimsAMissingBatch))  # status unchanged: SUCCESSFUL
        (failed,) = [e for e in job.results["error"] if e["message_code"] == "PRODUCED_BATCH_LINK_FAILED"]
        assert failed["message_data"]["disposition"] == "skipped"
        assert "DoesNotExist" in failed["message_data"]["error"]

    @SPEC[4]
    def test_two_jobs_claiming_the_same_batches_in_opposite_orders_do_not_deadlock(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each job checks one batch under its row lock, then waits until the other has checked one.

        Locked in the order each run reported them, each job would hold one batch's row while
        waiting for the other's, a deadlock Postgres breaks by failing one claim. Locked in batch-id
        order, both start with the same batch: the second waits for the first to commit, then
        finds both batches held and records two refusals, with nothing failed.
        """
        from django.db import transaction

        from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
        from tap_grid import batch as batch_module
        from tap_grid.batch import create_batch
        from tap_grid.cascade_corpus.timing import finish, in_thread

        silent = _register("silent", Silent)
        first_job, second_job = _run(silent), _run(silent)
        a, b = (str(create_batch(name=f"lock-order {n}", description="fixture").entity_id) for n in "ab")
        both_checked = threading.Barrier(2, timeout=3)
        real_imported_by = batch_module.imported_by
        waited = threading.local()

        def check_then_wait(batch_entity_id: Any) -> list[str]:
            holders = real_imported_by(batch_entity_id)
            if not getattr(waited, "once", False):
                waited.once = True
                try:
                    both_checked.wait()
                except threading.BrokenBarrierError:
                    pass  # the other job is queued on this one's row lock, which is the point
            return holders

        monkeypatch.setattr(batch_module, "imported_by", check_then_wait)

        def link(job: CollectionJob, claims: list[tuple[str, str]]) -> list[dict[str, Any]]:
            with acting_as(get_builtin_actor(COLLECTOR), batch_name="lock order", batch_description="fixture"):
                with transaction.atomic():  # held to the end, as the terminal transaction holds it
                    return _link_produced_batches(job, claims)

        first = in_thread(lambda: link(first_job, [(a, "imported"), (b, "imported")]))
        second = in_thread(lambda: link(second_job, [(b, "imported"), (a, "imported")]))
        finish(first, second)
        outcomes = [first[1].value, second[1].value]
        codes = sorted(entry["code"] for outcome in outcomes for entry in outcome)
        assert codes == ["PRODUCED_BATCH_CONFLICT", "PRODUCED_BATCH_CONFLICT"], outcomes
        assert sorted([imported_by(a)[0], imported_by(b)[0]]) in (
            [str(first_job.entity_id)] * 2,
            [str(second_job.entity_id)] * 2,
        ), "one job holds both batches"
