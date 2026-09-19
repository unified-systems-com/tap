"""The reconcile verb: authority on (Issue# 652 - tap, phase 4 slice 4).

``req-grid-reconcile-verb``: one service-layer verb judges a run's candidates under a budget
and applies the verdicts through the delete and patch verbs behind a freshness fence. The
fixture graph and the run come from the slice-2 and slice-3 suites: P contains c1..c3, this
run observed P and c1, c2 → c3 is the candidate. Every case that applies a write asserts the
exact rows it touched and nothing else.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied

from tap_grid.batch import close_batch
from tap_grid.candidates import record_candidates
from tap_grid.cascade_corpus.timing import JOIN_SECONDS, finish, in_thread
from tap_grid.falsifier_testing import FakeSource, FakeSourceFalsifier
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    JUDGED,
    NOT_JUDGED,
    PRESENT_AT_PROBE,
    RELOCATED,
    UNDETERMINED,
    Falsifier,
    FalsifyContext,
    Verdict,
    register_falsifier,
    unregister_falsifier,
    verdicts_of,
)
from tap_grid.models import Batch, BatchEvent, BatchEventType, Edge, Entity
from tap_grid.reconcile import APPLIED, NOT_APPLICABLE, RECONCILE_METADATA_KEY, REJECTED_STALE, ReconcileError
from tap_grid.services import get_node, reconcile
from tap_grid.tests.test_read_guard import _viewer_ctx
from tap_grid.tests.test_reconcile_candidates import CONTAINS, SOURCE, TARGET, Graph, _node, _run, _surface, batch

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.grid_fixtures.models import ConstrainedSource

    monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (CONTAINS,), raising=False)


@pytest.fixture(autouse=True)
def clean_registry() -> Any:
    unregister_falsifier(TARGET)
    yield
    unregister_falsifier(TARGET)


@pytest.fixture
def graph() -> Graph:
    return Graph()


def _snapshot() -> dict[uuid.UUID, tuple[bool, int, str]]:
    return {e.pk: (e.deleted_at is not None, e.version, e.name) for e in Entity.objects.exclude(entity_type="batch")}


def _run_with_candidates(graph: Graph, *observed: Entity) -> tuple[Batch, set[str]]:
    """P's surface complete; the given children observed → the rest are candidates."""
    write = graph.observe(graph.p, *observed)
    run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
    record_candidates(run, produced_batches=[str(write.entity_id)])
    run.refresh_from_db()
    return run, {str(write.entity_id)}


def _source_for(graph: Graph, *children: Entity) -> FakeSource:
    source = FakeSource()
    for child in children:
        source.holds(child.pk, f"src-{child.name}", owner=str(graph.p.pk), name=child.name)
    return source


class TestAuthorityOff:
    @pytest.mark.spec("req-grid-reconcile-verb-2")
    def test_off_by_default_judges_nothing_and_says_so(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = reconcile(run.entity_id, produced_batches=produced)

        assert record["authority"] == "off" and record["candidates"] == 1
        [entry] = record["entries"]
        assert entry["outcome"] == NOT_JUDGED and entry["verdict"] is None and entry["applied"] is None
        assert "authority is off" in entry["note"]
        assert record["applied"] == {
            "authority": "off",
            "applied": 0,
            "rejected_stale": 0,
            "refused": 0,
            "not_applicable": 0,
        }
        assert source.calls == 0, "no probe ran"
        assert _snapshot() == before
        run.refresh_from_db()
        assert verdicts_of(run) == record

    def test_the_verb_needs_its_own_capability(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        with pytest.raises(PermissionDenied):
            reconcile(run.entity_id, caller_context=_viewer_ctx(), produced_batches=produced)
        run.refresh_from_db()
        assert verdicts_of(run) is None

    def test_refusals_write_nothing(self, graph: Graph) -> None:
        run = _run(_surface(graph.p))
        with pytest.raises(ReconcileError) as excinfo:
            reconcile(run.entity_id, authority=True)
        assert excinfo.value.code == "no_candidates"
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        close_batch(run)
        with pytest.raises(ReconcileError) as excinfo:
            reconcile(run.entity_id, authority=True)
        assert excinfo.value.code == "batch_not_open"

    @pytest.mark.spec("req-grid-reconcile-verb-6")
    def test_there_is_one_public_entry_point(self) -> None:
        from tap_grid import services

        assert "reconcile" in services.__all__
        assert not [name for name in services.__all__ if name.startswith(("falsify", "apply_verdict", "reconcile_"))]


@pytest.mark.spec("req-grid-reconcile-verb-3")
class TestBudget:
    def test_the_budget_bounds_the_pass_and_the_run_succeeds(
        self, graph: Graph, caplog: pytest.LogCaptureFixture
    ) -> None:
        from tap_grid.services import create_edge

        with batch("test.reconcile.more"):
            extra = [_node(TARGET, f"x{i}") for i in range(14)]
            for child in extra:
                create_edge(graph.p, child, CONTAINS)
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        candidates = [graph.c[2], *extra]
        source = _source_for(graph, *candidates)
        for child in candidates:
            source.dropped(child.pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        with caplog.at_level("WARNING"):
            record = reconcile(run.entity_id, authority=True, budget=5, produced_batches=produced)

        assert record["budget"] == {"limit": 5, "used": 5, "left": 10}
        assert source.calls == 1 and len(source.answers) == 15
        judged = [e for e in record["entries"] if e["verdict"] == DROPPED_FROM_OBSERVATION]
        left = [e for e in record["entries"] if e["verdict"] == UNDETERMINED and e["reason"] == "budget"]
        assert len(judged) == 5 and len(left) == 10
        assert all(e["applied"]["outcome"] == APPLIED for e in judged)
        assert all(e["applied"]["outcome"] == NOT_APPLICABLE for e in left)
        assert record["applied"]["applied"] == 5 and record["applied"]["not_applicable"] == 10
        assert Entity.objects.filter(pk__in=[c.pk for c in candidates], deleted_at__isnull=False).count() == 5
        assert any("[edf1]" in r.message and "10 left" in r.message for r in caplog.records)


class TestApplying:
    @pytest.mark.spec("req-grid-reconcile-falsifier-3")
    def test_dropped_is_tombstoned_with_the_candidates_reason_and_the_audit(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = reconcile(run.entity_id, authority=True, budget=10, produced_batches=produced)

        [entry] = record["entries"]
        assert entry["applied"] == {"write": "tombstone", "outcome": APPLIED, "error": None}
        assert record["authority"] == "on" and record["applied"]["applied"] == 1
        gone = Entity.objects.get(pk=graph.c[2].pk)
        assert gone.deleted_at is not None
        event = BatchEvent.objects.get(entity_id=graph.c[2].pk, event_type=BatchEventType.DELETE)
        assert event.metadata["reason"] == "dropped_from_observation"
        assert event.metadata[RECONCILE_METADATA_KEY]["run"] == str(run.entity_id)
        assert event.metadata[RECONCILE_METADATA_KEY]["verdict"] == DROPPED_FROM_OBSERVATION
        after = _snapshot()
        changed = {k for k in after if after[k] != before.get(k)}
        assert changed == {graph.c[2].pk} | {
            e.entity_id for e in Edge.all_objects.filter(to_entity_id=graph.c[2].pk)
        }, "only the candidate and its edges moved"

    @pytest.mark.spec("req-grid-reconcile-falsifier-8")
    def test_a_rename_updates_the_name_and_retires_nothing(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.renamed(graph.c[2].pk, "c3, renamed")
        register_falsifier(TARGET, FakeSourceFalsifier(source))

        [entry] = reconcile(run.entity_id, authority=True, produced_batches=produced)["entries"]

        assert entry["verdict"] == RELOCATED and entry["applied"] == {
            "write": "rename",
            "outcome": APPLIED,
            "error": None,
        }
        row = Entity.objects.get(pk=graph.c[2].pk)
        assert row.deleted_at is None and row.name == "c3, renamed"
        assert get_node(graph.c[2].pk).name == "c3, renamed"

    @pytest.mark.spec("req-grid-reconcile-falsifier-7")
    @pytest.mark.spec("req-grid-reconcile-falsifier-9")
    def test_a_transfer_ends_this_parents_edge_only_and_cascades_nothing(self, graph: Graph) -> None:
        """Asserted on a parent with children: c3 gets a child of its own, is transferred away
        from P, and neither c3 nor its child retires — only P's containment edge into c3 ends."""
        from tap_grid.services import create_edge
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        with batch("test.reconcile.grandchild"):
            grandchild = _node(TARGET, "c3's child")
            create_edge(graph.c[2], grandchild, "NESTING_LINK__grid_fixtures")
        pytest.MonkeyPatch().setattr(
            ConstrainedTarget, "CONTAINMENT_EDGES", ("NESTING_LINK__grid_fixtures",), raising=False
        )
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.transferred(graph.c[2].pk, "someone-else")
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        [entry] = reconcile(run.entity_id, authority=True, produced_batches=produced)["entries"]

        assert entry["kind"] == "transferred"
        assert entry["applied"] == {"write": "end_ownership_edge", "outcome": APPLIED, "error": None}
        edge = Edge.all_objects.get(from_entity_id=graph.p.pk, to_entity_id=graph.c[2].pk, edge_type=CONTAINS)
        assert edge.entity.deleted_at is not None, "P's edge into c3 ended"
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is None
        assert Entity.objects.get(pk=grandchild.pk).deleted_at is None
        assert not BatchEvent.objects.filter(
            entity_id__in=[graph.c[2].pk, grandchild.pk], event_type=BatchEventType.DELETE
        ).exists()
        after = _snapshot()
        assert {k for k in after if after[k] != before.get(k)} == {edge.entity_id}

    def test_present_and_undetermined_apply_nothing(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.present(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()
        [entry] = reconcile(run.entity_id, authority=True, produced_batches=produced)["entries"]
        assert entry["verdict"] == PRESENT_AT_PROBE and entry["applied"]["outcome"] == NOT_APPLICABLE
        assert _snapshot() == before


@pytest.mark.spec("req-grid-reconcile-verb-4")
class TestTheFence:
    def test_a_re_observation_after_derivation_rejects_the_verdict_even_without_a_version_bump(
        self, graph: Graph
    ) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        version_before = Entity.objects.get(pk=graph.c[2].pk).version
        later = graph.observe(graph.c[2])  # another writer re-observes c3, unchanged, and commits
        assert (
            Entity.objects.get(pk=graph.c[2].pk).version == version_before
        ), "an unchanged re-observation bumps nothing"
        assert later.entity_id not in {uuid.UUID(b) for b in produced}
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = reconcile(run.entity_id, authority=True, produced_batches=produced)

        [entry] = record["entries"]
        assert entry["verdict"] == DROPPED_FROM_OBSERVATION
        assert entry["applied"]["outcome"] == REJECTED_STALE and "re-observed" in entry["applied"]["error"]
        assert record["applied"]["rejected_stale"] == 1 and record["applied"]["applied"] == 0
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is None
        assert _snapshot() == before

    def test_this_runs_own_observations_are_not_re_observations(self, graph: Graph) -> None:
        """The run that produced the observed set owns it: its own batches never fence its verdicts."""
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        [entry] = reconcile(run.entity_id, authority=True, produced_batches=produced)["entries"]
        assert entry["applied"]["outcome"] == APPLIED


class TestWithdrawal:
    @pytest.mark.spec("req-grid-reconcile-verb-7")
    def test_an_unknown_previous_scope_withdraws_nothing(self, graph: Graph) -> None:
        """No previous run offered: withdrawal is not observable, so no scope_withdrawn candidate
        exists for the verb to act on — Q's children stay live whatever the falsifier would say."""
        write = graph.observe(graph.p, *graph.c)  # Q is not in this run's scope at all
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record_candidates(run, produced_batches=[str(write.entity_id)])  # previous_batch omitted: unknown
        run.refresh_from_db()
        source = _source_for(graph, *graph.qs)
        for q in graph.qs:
            source.dropped(q.pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = reconcile(run.entity_id, authority=True, produced_batches={str(write.entity_id)})

        assert not [e for e in record["entries"] if e["candidate_reason"] == "scope_withdrawn"]
        assert record["applied"]["applied"] == 0 and _snapshot() == before

    @pytest.mark.spec("req-grid-reconcile-verb-8")
    def test_a_withdrawal_retires_through_the_same_path(self, graph: Graph) -> None:
        """The previous run held Q in scope and observed q1, q2; this run declares only P. The
        withdrawn children are retired with reason scope_withdrawn through the same verb, fence,
        cascade and audit as a dropped candidate."""
        previous_write = graph.observe(graph.p, graph.q, *graph.c, *graph.qs)
        previous = _run(
            _surface(graph.p, applied_batches=[str(previous_write.entity_id)]),
            _surface(graph.q, applied_batches=[str(previous_write.entity_id)]),
        )
        record_candidates(previous, produced_batches=[str(previous_write.entity_id)])
        close_batch(previous)
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(previous_write.entity_id)],
        )
        run.refresh_from_db()
        source = _source_for(graph, *graph.qs)
        for q in graph.qs:
            source.dropped(q.pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))

        record = reconcile(run.entity_id, authority=True, produced_batches={str(write.entity_id)})

        withdrawn = [e for e in record["entries"] if e["candidate_reason"] == "scope_withdrawn"]
        assert {e["entity_id"] for e in withdrawn} == {str(q.pk) for q in graph.qs}
        assert all(e["applied"]["outcome"] == APPLIED for e in withdrawn)
        for q in graph.qs:
            event = BatchEvent.objects.get(entity_id=q.pk, event_type=BatchEventType.DELETE)
            assert event.metadata["reason"] == "scope_withdrawn"
            assert event.metadata[RECONCILE_METADATA_KEY]["candidate_reason"] == "scope_withdrawn"
            assert event.metadata[RECONCILE_METADATA_KEY]["run"] == str(run.entity_id)
        assert Entity.objects.get(pk=graph.q.pk).deleted_at is None, "Q itself was never a candidate"


@pytest.mark.django_db(transaction=True)
@pytest.mark.spec("req-grid-reconcile-verb-5")
class TestAtomicity:
    def test_two_concurrent_reconciles_of_one_candidate_yield_one_tombstone(self, graph: Graph) -> None:
        """Both runs judge the same absent object; the tombstone is written once, the second
        application is the pipeline's noop on an already-tombstoned row, and no edge is left
        pointing at anything that lost."""
        run_a, produced_a = _run_with_candidates(graph, graph.c[0], graph.c[1])
        run_b, produced_b = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        barrier = threading.Barrier(2, timeout=JOIN_SECONDS)

        def writer(run: Batch, produced: set[str]) -> Any:
            def go() -> Any:
                barrier.wait()
                return reconcile(run.entity_id, authority=True, produced_batches=produced)

            return go

        first, second = in_thread(writer(run_a, produced_a)), in_thread(writer(run_b, produced_b))
        finish(first, second)
        outcomes = sorted(r[1].value["entries"][0]["applied"]["outcome"] for r in (first, second))
        assert outcomes == [APPLIED, APPLIED], "the second application is the pipeline's noop, reported as applied"
        assert BatchEvent.objects.filter(entity_id=graph.c[2].pk, event_type=BatchEventType.DELETE).count() == 1
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is not None
        assert not Edge.objects.filter(to_entity_id=graph.c[2].pk).exists(), "no live edge points at the tombstone"


class TestRecordShape:
    def test_a_judged_record_carries_parent_and_edge_type_for_the_transfer_write(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])

        class Budgetless(Falsifier):
            def batch_falsify(self, candidates: Any, context: FalsifyContext) -> list[Verdict]:
                return [
                    Verdict(c.entity_id, UNDETERMINED, reason="scope_unknown", surface=c.surface) for c in candidates
                ]

        register_falsifier(TARGET, Budgetless())
        [entry] = reconcile(run.entity_id, authority=True, produced_batches=produced)["entries"]
        assert entry["outcome"] == JUDGED and entry["parent"] == str(graph.p.pk) and entry["edge_type"] == CONTAINS
        assert entry["applied"]["outcome"] == NOT_APPLICABLE

    def test_the_source_and_target_are_untouched_by_a_present_verdict(self, graph: Graph) -> None:
        assert SOURCE and TARGET  # the fixture types this suite rests on
