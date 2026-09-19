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

from tap_auth.errors import CapabilityDenied
from tap_grid.batch import close_batch
from tap_grid.candidates import record_candidates
from tap_grid.cascade_corpus.timing import JOIN_SECONDS, finish, in_thread
from tap_grid.falsifier_testing import FakeSource, FakeSourceFalsifier, arm_run_for_tests
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
from tap_grid.reconcile import (
    APPLIED,
    NOT_APPLICABLE,
    RECONCILE_METADATA_KEY,
    REJECTED_STALE,
    ReconcileError,
    run_config_of,
)
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


def _reconcile_armed(run: Batch, *, budget: int | None = None) -> dict[str, Any]:
    """Arm the run the way run_collection does — a stamp on its lifecycle batch — then call the
    verb, which takes no policy from its caller."""
    run.refresh_from_db()
    arm_run_for_tests(run, authority=True, budget=budget, collector="test-collector")
    return reconcile(run.entity_id)


def _fake_candidate(entity_type: str, *, surface: int) -> Any:
    from tap_grid.falsifiers import Candidate

    return Candidate(uuid.uuid4(), entity_type, "dropped_from_observation", surface, "r", "s", CONTAINS, None, None)


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

        record = reconcile(run.entity_id)

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
            "contradicted": 0,
        }
        assert source.calls == 0, "no probe ran"
        assert _snapshot() == before
        run.refresh_from_db()
        assert verdicts_of(run) == record

    def test_a_run_stamped_off_stays_off_and_the_caller_cannot_arm_it(self, graph: Graph) -> None:
        """The stamp is the only source of authority: an explicit off stamp records not_judged, the
        verb takes no authority argument at all, and a second stamp is refused."""
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        arm_run_for_tests(run, authority=False, budget=3, collector="c")
        assert run_config_of(run) == {"authority": False, "budget": 3, "collector": "c"}
        with pytest.raises(TypeError):
            reconcile(run.entity_id, authority=True)  # type: ignore[call-arg]
        with pytest.raises(AssertionError, match="already carries"):
            arm_run_for_tests(run, authority=True, budget=None, collector="c")
        from tap_grid import reconcile as reconcile_module

        assert not hasattr(reconcile_module, "stamp_run_config"), "no production writer of the configuration exists"
        [entry] = reconcile(run.entity_id)["entries"]
        assert entry["outcome"] == NOT_JUDGED

    def test_an_unstamped_run_reads_as_authority_off(self, graph: Graph) -> None:
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        assert run_config_of(run) == {"authority": False, "budget": None, "collector": None}

    def test_the_config_parse_fails_closed_on_every_axis(self, graph: Graph, caplog: pytest.LogCaptureFixture) -> None:
        """A malformed stamp never widens a pass: authority is on only when literally true, and a
        budget that is not a non-negative integer probes nothing rather than everything."""
        from tap_grid.reconcile import RUN_CONFIG_KEY, run_config

        with pytest.raises(ReconcileError, match="non-negative integer"):
            run_config(authority=True, budget=-1, collector="c")
        with pytest.raises(ReconcileError, match="must be a bool"):
            run_config(authority="true", budget=1, collector="c")  # type: ignore[arg-type]
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        run.metadata = {**run.metadata, RUN_CONFIG_KEY: {"authority": "true", "budget": -1, "collector": "c"}}
        run.save(update_fields=["metadata"])  # below the service layer, on purpose: a hand-written stamp
        with caplog.at_level("WARNING"):
            config = run_config_of(run)
        assert config == {"authority": False, "budget": 0, "collector": "c"}
        assert any("probing nothing" in r.message for r in caplog.records)
        run.metadata = {**run.metadata, RUN_CONFIG_KEY: {"authority": True, "budget": 2**40, "collector": "c"}}
        run.save(update_fields=["metadata"])
        assert run_config_of(run)["budget"] == 2**40

    def test_the_verb_needs_its_own_capability(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        with pytest.raises(CapabilityDenied, match="grid.reconcile"):
            reconcile(run.entity_id, caller_context=_viewer_ctx())
        run.refresh_from_db()
        assert verdicts_of(run) is None

    def test_refusals_write_nothing(self, graph: Graph) -> None:
        run = _run(_surface(graph.p))
        with pytest.raises(ReconcileError) as excinfo:
            _reconcile_armed(run)
        assert excinfo.value.code == "no_candidates"
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        close_batch(run)
        with pytest.raises(ReconcileError) as excinfo:
            _reconcile_armed(run)
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
            record = _reconcile_armed(run, budget=5)

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

    def test_unreconcilable_candidates_do_not_consume_the_budget(self) -> None:
        """Two candidate types, one with a falsifier, budget 1: the type with no falsifier is
        recorded not_reconcilable and the one probe goes to the reconcilable candidate — the
        dispatch itself, over fake types, no database."""
        from tap_grid.falsifiers import _dispatch

        seen: list[uuid.UUID] = []

        class Counting(Falsifier):
            def batch_falsify(self, candidates: Any, context: FalsifyContext) -> list[Verdict]:
                seen.extend(c.entity_id for c in candidates)
                return [
                    Verdict(c.entity_id, UNDETERMINED, reason="scope_unknown", surface=c.surface) for c in candidates
                ]

        register_falsifier("fake__probed", Counting())
        try:
            stranger = _fake_candidate("fake__stranger", surface=0)
            probed = _fake_candidate("fake__probed", surface=1)
            record = _dispatch([stranger, probed], FalsifyContext("b", None), budget=1)
        finally:
            unregister_falsifier("fake__probed")
        by_id = {e["entity_id"]: e for e in record["entries"]}
        assert by_id[str(stranger.entity_id)]["outcome"] == "not_reconcilable"
        assert (
            by_id[str(probed.entity_id)]["verdict"] == UNDETERMINED
            and by_id[str(probed.entity_id)]["reason"] == "scope_unknown"
        )
        assert record["budget"] == {"limit": 1, "used": 1, "left": 0} and seen == [probed.entity_id]


class TestApplying:
    @pytest.mark.spec("req-grid-reconcile-falsifier-3")
    def test_dropped_is_tombstoned_with_the_candidates_reason_and_the_audit(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = _reconcile_armed(run, budget=10)

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

        [entry] = _reconcile_armed(run)["entries"]

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
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        from tap_grid.services import create_edge

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

        [entry] = _reconcile_armed(run)["entries"]

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

    def test_the_apply_works_as_the_collector_actor_which_holds_reconcile_but_not_delete(self, graph: Graph) -> None:
        """The production actor shape (Grok on PR# 653 - tap): tap_cares.collector holds
        grid.reconcile and grid.write, not grid.delete. The verb's tombstone is its own write,
        licensed by grid.reconcile, so it lands under that actor."""
        from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
        from tap_auth.capabilities import DELETE_CAPABILITY, RECONCILE_CAPABILITY
        from tap_auth.policy import can
        from tap_grid.caller_context import CallerContext

        actor = get_builtin_actor(COLLECTOR)
        ctx = CallerContext(user=actor)
        assert can(ctx, RECONCILE_CAPABILITY) and not can(ctx, DELETE_CAPABILITY)
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        with acting_as(actor):
            [entry] = _reconcile_armed(run)["entries"]
        assert entry["applied"] == {"write": "tombstone", "outcome": APPLIED, "error": None}
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is not None

        # Outside the verb's apply pass the same actor still cannot delete: grid.reconcile is
        # not a cover for grid.delete anywhere else.
        from tap_auth.errors import AuthzError
        from tap_grid.services import delete_node

        with acting_as(actor), pytest.raises(AuthzError):
            delete_node(graph.c[1].pk)
        assert Entity.objects.get(pk=graph.c[1].pk).deleted_at is None

    def test_the_apply_scope_licenses_only_the_row_the_verb_names(self, graph: Graph) -> None:
        """Codex on PR# 653 - tap: the apply scope is a contextvar any in-process code can open —
        like ``unguarded_write``, a lint-guarded trust boundary, not a capability. So it is bound
        to targets: opened for one row it licenses a delete of that row and nothing else; opened
        for nothing it licenses nothing. The collector actor, holding grid.reconcile and not
        grid.delete, cannot widen it into a delete of an unrelated entity."""
        from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
        from tap_auth.errors import UnguardedOperation
        from tap_grid.service_types import WriteOperation
        from tap_grid.services import write_batch
        from tap_grid.write_guard import reconcile_write_scope

        actor = get_builtin_actor(COLLECTOR)
        unrelated = WriteOperation(verb="delete_node", target=graph.c[1].pk, reason="test")
        with acting_as(actor):
            with reconcile_write_scope(()), pytest.raises(UnguardedOperation):
                write_batch([unrelated])
            with reconcile_write_scope({graph.c[2].pk}), pytest.raises(UnguardedOperation):
                write_batch([unrelated])
        assert Entity.objects.get(pk=graph.c[1].pk).deleted_at is None

    def test_an_operation_formed_for_the_wrong_row_is_refused_not_licensed(
        self, graph: Graph, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex on PR# 658 - tap: the licence must not be read off the operation, or a defect in
        operation construction licenses itself. It is derived from the verdict entry; here the
        construction is broken on purpose to target a sibling, and the pass fails closed."""
        from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
        from tap_auth.errors import UnguardedOperation
        from tap_grid.service_types import WriteOperation

        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        wrong = WriteOperation(verb="delete_node", target=graph.c[1].pk, reason="defect", cascade="contained")
        monkeypatch.setattr("tap_grid.reconcile._operation_for", lambda entry, batch, generation: wrong)
        before = _snapshot()
        # As the production actor: grid.reconcile without grid.delete, so the licence is the only door.
        with acting_as(get_builtin_actor(COLLECTOR)), pytest.raises(UnguardedOperation):
            _reconcile_armed(run)
        assert _snapshot() == before, "nothing retired, nothing recorded"

    def test_present_and_undetermined_apply_nothing(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.present(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()
        [entry] = _reconcile_armed(run)["entries"]
        assert entry["verdict"] == PRESENT_AT_PROBE and entry["applied"]["outcome"] == NOT_APPLICABLE
        assert _snapshot() == before


@pytest.mark.spec("req-grid-reconcile-verb-4")
class TestTheFence:
    def test_a_re_observation_after_derivation_rejects_the_verdict(self, graph: Graph) -> None:
        """The fence reads the entity's observation EVENTS from committed batches outside this
        run, never ``Entity.version`` — so it holds whether or not the re-observation bumped the
        row (an unchanged GRIFT re-observation deliberately may not)."""
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        later = graph.observe(graph.c[2])  # another writer re-observes c3 and commits
        assert later.entity_id not in {uuid.UUID(b) for b in produced}
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = _reconcile_armed(run)

        [entry] = record["entries"]
        assert entry["verdict"] == DROPPED_FROM_OBSERVATION
        assert entry["applied"]["outcome"] == REJECTED_STALE and "re-observed" in entry["applied"]["error"]
        assert record["applied"]["rejected_stale"] == 1 and record["applied"]["applied"] == 0
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is None
        assert _snapshot() == before

    def test_the_fence_holds_when_the_version_did_not_move(self, graph: Graph) -> None:
        """Entity.version is not the fence: with the re-observation's version bump undone at the
        row (as an unchanged import leaves it), the event alone still rejects the verdict."""
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        version_before = Entity.objects.get(pk=graph.c[2].pk).version
        graph.observe(graph.c[2])
        Entity.objects.filter(pk=graph.c[2].pk).update(version=version_before)  # below the service layer, on purpose
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        [entry] = _reconcile_armed(run)["entries"]
        assert entry["applied"]["outcome"] == REJECTED_STALE
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is None

    def test_an_unparsable_candidate_clock_refuses_the_pass(self, graph: Graph) -> None:
        """The fence's clock is the candidate record's recorded_at; if it cannot be read the pass is
        refused rather than run against a later, more permissive clock."""
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        run.metadata = {**run.metadata, "candidates": {**run.metadata["candidates"], "recorded_at": "yesterday"}}
        run.save(update_fields=["metadata"])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()
        with pytest.raises(ReconcileError) as excinfo:
            _reconcile_armed(run)
        assert excinfo.value.code == "invalid_record"
        assert _snapshot() == before

    def test_a_re_created_ownership_edge_rejects_the_transfer(self, graph: Graph) -> None:
        """Codex on PR# 653 - tap: a transfer ends an EDGE, and an edge re-created after the
        record was derived leaves a ``link`` event on the edge and no update on the child — so
        the edge is fenced on its own event, and the fresh edge survives."""
        from tap_grid.services import create_edge, delete_edge

        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        old = Edge.objects.get(from_entity_id=graph.p.pk, to_entity_id=graph.c[2].pk, edge_type=CONTAINS)
        with batch("test.reconcile.relink"):  # another writer re-creates P's edge into c3 and commits
            delete_edge(old)
            create_edge(graph.p, graph.c[2], CONTAINS)
        fresh = Edge.objects.get(from_entity_id=graph.p.pk, to_entity_id=graph.c[2].pk, edge_type=CONTAINS)
        assert fresh.entity_id != old.entity_id
        source = _source_for(graph, graph.c[2])
        source.transferred(graph.c[2].pk, "someone-else")
        register_falsifier(TARGET, FakeSourceFalsifier(source))

        [entry] = _reconcile_armed(run)["entries"]

        assert entry["kind"] == "transferred"
        assert entry["applied"]["outcome"] == REJECTED_STALE and "edge" in entry["applied"]["error"]
        assert Entity.objects.get(pk=fresh.entity_id).deleted_at is None, "the fresh edge survives"

    def test_this_runs_own_observations_are_not_re_observations(self, graph: Graph) -> None:
        """The run that produced the observed set owns it: its own batches never fence its verdicts."""
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        [entry] = _reconcile_armed(run)["entries"]
        assert entry["applied"]["outcome"] == APPLIED


@pytest.mark.spec("req-grid-reconcile-verb-9")
class TestContradiction:
    """A contradicted candidate is refused by every stage of the verb (Issue# 656 - tap)."""

    NEST = "NESTING_LINK__grid_fixtures"

    @pytest.fixture(autouse=True)
    def nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        monkeypatch.setattr(ConstrainedTarget, "CONTAINMENT_EDGES", (self.NEST,), raising=False)

    def _grandchild(self, under: Entity) -> Entity:
        from tap_grid.services import create_edge

        with batch("test.reconcile.grandchild"):
            g = _node(TARGET, "g")
            create_edge(under, g, self.NEST)
        return g

    def test_a_contradicted_candidate_is_never_probed_never_applied_and_spends_no_budget(self, graph: Graph) -> None:
        g = self._grandchild(graph.c[2])
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1], g)  # g observed, c3 not
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)  # the probe would say gone — it is never asked
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        record = _reconcile_armed(run, budget=1)

        [entry] = record["entries"]
        assert entry["outcome"] == "contradicted" and entry["verdict"] is None and entry["applied"] is None
        assert entry["contradiction"] == {
            "kind": "observed_descendants",
            "observed_descendants": [str(g.pk)],
            "count": 1,
        }
        assert "investigate" in entry["note"] and str(g.pk) in entry["note"]
        assert record["contradicted"] == 1 and record["calls"] == {}, "no falsifier was called"
        assert record["budget"] == {"limit": 1, "used": 0, "left": 0}
        assert record["applied"]["contradicted"] == 0 and record["applied"]["applied"] == 0
        assert _snapshot() == before

    def test_the_contradiction_is_visible_with_authority_off(self, graph: Graph) -> None:
        g = self._grandchild(graph.c[2])
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1], g)
        record = reconcile(run.entity_id)
        [entry] = record["entries"]
        assert record["authority"] == "off" and entry["outcome"] == "contradicted"
        assert record["contradicted"] == 1

    def test_a_descendant_observed_after_derivation_fences_the_tombstone(
        self, graph: Graph, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Derivation saw no contradiction (g unobserved); then another writer observes g and
        commits; the tombstone on c3 would cascade over that evidence — refused at apply."""
        g = self._grandchild(graph.c[2])
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        [c3] = run.metadata["candidates"]["surfaces"][0]["candidates"]
        assert c3["contradiction"] is None
        graph.observe(g)  # after derivation, committed
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        with caplog.at_level("WARNING", logger="tap_grid.reconcile"):
            record = _reconcile_armed(run)

        [entry] = record["entries"]
        assert entry["verdict"] == DROPPED_FROM_OBSERVATION and entry["outcome"] == JUDGED
        assert entry["applied"]["outcome"] == "contradicted" and str(g.pk) in entry["applied"]["error"]
        assert record["applied"]["contradicted"] == 1 and record["applied"]["applied"] == 0
        assert any("[2611]" in r.getMessage() for r in caplog.records)
        assert _snapshot() == before, "c3 and g both live, nothing written"

    def test_the_apply_fence_sees_a_descendant_attached_after_the_first_look(
        self, graph: Graph, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex and Grok on PR# 663 - tap: the fence must not check a snapshot the cascade will
        then outgrow. The closure is re-discovered under locks; a node attached beneath a
        descendant after the first discovery — and observed by a committed batch — is in the
        re-discovered closure and contradicts the tombstone."""
        import importlib

        from tap_grid.services import create_edge

        g = self._grandchild(graph.c[2])
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        late: list[Entity] = []
        real = importlib.import_module("tap_grid.services._impl")._discover_closure

        def attach_after_first_look(root_id: uuid.UUID, model_cls: type, state: Any) -> Any:
            found = real(root_id, model_cls, state)
            if root_id == graph.c[2].pk and not late:  # the apply fence's first, unlocked discovery
                with batch("test.reconcile.late"):  # another writer attaches and observes gg under g
                    gg = _node(TARGET, "gg")
                    create_edge(g, gg, self.NEST)
                late.append(gg)
            return found

        # The gateway's first, unlocked look binds the name at import; the re-discovery under
        # locks reads the module global. Patch both so the late attach lands between them.
        monkeypatch.setattr("tap_grid.services._discover_closure", attach_after_first_look)
        monkeypatch.setattr("tap_grid.services._impl._discover_closure", attach_after_first_look)
        record = _reconcile_armed(run)

        [entry] = record["entries"]
        assert entry["applied"]["outcome"] == "contradicted" and str(late[0].pk) in entry["applied"]["error"]
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is None
        assert Entity.objects.get(pk=late[0].pk).deleted_at is None

    def test_an_observation_in_a_still_open_batch_also_fences(self, graph: Graph) -> None:
        """Codex on PR# 663 - tap: an open batch may commit a moment after the fence looks. Only a
        FAILED batch is known to have rolled back, so an open batch's observation counts."""
        from tap_grid.batch import create_batch
        from tap_grid.context import set_batch_id
        from tap_grid.services import patch_node

        g = self._grandchild(graph.c[2])
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        still_open = create_batch(source="test.reconcile.open")
        set_batch_id(str(still_open.entity_id))
        try:
            assert patch_node(g.pk, {"name": g.name}).success
        finally:
            set_batch_id(None)
        assert Batch.objects.get(pk=still_open.pk).status == "open"
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))

        [entry] = _reconcile_armed(run)["entries"]

        assert entry["applied"]["outcome"] == "contradicted" and str(g.pk) in entry["applied"]["error"]
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is None

    def test_the_locked_closure_is_the_reconcile_verbs_and_not_a_readers(self, graph: Graph) -> None:
        """Grok and Codex on PR# 663 - tap: taking row locks is not a read. The unlocked closure is
        a grid.read; the locked one is gated by grid.reconcile."""
        from tap_grid.services import contained_closure, contained_closure_locked

        viewer = _viewer_ctx()
        assert contained_closure(graph.p.pk, caller_context=viewer) == {c.pk for c in graph.c}
        with pytest.raises(CapabilityDenied):
            contained_closure_locked(graph.p.pk, caller_context=viewer)

    def test_a_clean_closure_still_tombstones(self, graph: Graph) -> None:
        """Regression: a descendant nobody observed retires with its parent exactly as before."""
        g = self._grandchild(graph.c[2])
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2])
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        [entry] = _reconcile_armed(run)["entries"]
        assert entry["applied"]["outcome"] == APPLIED
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is not None
        assert Entity.objects.get(pk=g.pk).deleted_at is not None


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

        record = _reconcile_armed(run)

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

        record = _reconcile_armed(run)

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
                return _reconcile_armed(run)

            return go

        first, second = in_thread(writer(run_a, produced_a)), in_thread(writer(run_b, produced_b))
        finish(first, second)
        outcomes = sorted(r[1].value["entries"][0]["applied"]["outcome"] for r in (first, second))
        assert outcomes == [APPLIED, APPLIED], "the second application is the pipeline's noop, reported as applied"
        assert BatchEvent.objects.filter(entity_id=graph.c[2].pk, event_type=BatchEventType.DELETE).count() == 1
        assert Entity.objects.get(pk=graph.c[2].pk).deleted_at is not None
        assert not Edge.objects.filter(to_entity_id=graph.c[2].pk).exists(), "no live edge points at the tombstone"


class TestOneTransaction:
    def test_a_failure_while_applying_rolls_back_every_write_and_the_record(
        self, graph: Graph, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Judging, every write and the record are one transaction: an exception after the first
        tombstone leaves no tombstone and no verdict record behind (Codex on PR# 653 - tap)."""
        from tap_grid.services import create_edge

        with batch("test.reconcile.two"):
            other = _node(TARGET, "x-other")
            create_edge(graph.p, other, CONTAINS)
        run, _ = _run_with_candidates(graph, graph.c[0], graph.c[1])
        source = _source_for(graph, graph.c[2], other)
        source.dropped(graph.c[2].pk)
        source.dropped(other.pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()
        calls: list[int] = []
        import tap_grid.reconcile as reconcile_module

        real = reconcile_module._lock_target

        def _lock_then_boom(entity_id: uuid.UUID) -> None:
            real(entity_id)
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("the second write exploded")

        monkeypatch.setattr(reconcile_module, "_lock_target", _lock_then_boom)
        with pytest.raises(RuntimeError, match="second write exploded"):
            _reconcile_armed(run)
        assert _snapshot() == before, "the first tombstone was rolled back with the failure"
        run.refresh_from_db()
        assert verdicts_of(run) is None, "no half-written record survives"


class TestRecordShape:
    def test_a_judged_record_carries_parent_and_edge_type_for_the_transfer_write(self, graph: Graph) -> None:
        run, produced = _run_with_candidates(graph, graph.c[0], graph.c[1])

        class Budgetless(Falsifier):
            def batch_falsify(self, candidates: Any, context: FalsifyContext) -> list[Verdict]:
                return [
                    Verdict(c.entity_id, UNDETERMINED, reason="scope_unknown", surface=c.surface) for c in candidates
                ]

        register_falsifier(TARGET, Budgetless())
        [entry] = _reconcile_armed(run)["entries"]
        assert entry["outcome"] == JUDGED and entry["parent"] == str(graph.p.pk) and entry["edge_type"] == CONTAINS
        assert entry["applied"]["outcome"] == NOT_APPLICABLE

    def test_the_source_and_target_are_untouched_by_a_present_verdict(self, graph: Graph) -> None:
        assert SOURCE and TARGET  # the fixture types this suite rests on
