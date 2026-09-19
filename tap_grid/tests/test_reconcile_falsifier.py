"""Per-type falsifiers and their verdicts, authority off (Issue# 644 - tap, phase 4 slice 3).

``req-grid-reconcile-falsifier``: the classification is a pure table over what the probe
returned against what the grid holds; the dispatch runs each type's falsifier ONCE over
that type's candidates and RECORDS verdicts on the run's Batch beside its candidate record.
Nothing is retired, renamed or unlinked: every case ends by asserting the grid is exactly
as it was. The fixture graph, the run and its candidate record come from the slice-2 suite
(``test_reconcile_candidates``): P contains c1..c3, this run observed P and c1, c2 → c3 is
the candidate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from tap_grid.batch import batch_summary, close_batch
from tap_grid.candidates import record_candidates
from tap_grid.falsifier_testing import FOUR_CASES, FakeSource, FakeSourceFalsifier, run_four_cases
from tap_grid.falsifiers import (
    CAUSE_CREATED_AFTER,
    CAUSE_INDETERMINATE,
    DROPPED_FROM_OBSERVATION,
    JUDGED,
    NOT_RECONCILABLE,
    PRESENT_AT_PROBE,
    PRESENT_STATEMENT,
    REIDENTIFIED,
    RELOCATED,
    RELOCATED_RENAMED,
    RELOCATED_TRANSFERRED,
    UNDETERMINED,
    UNDETERMINED_REASONS,
    VERDICTS,
    Candidate,
    Expected,
    Falsifier,
    FalsifierError,
    FalsifyContext,
    Probe,
    Verdict,
    candidates_from,
    classify,
    falsify_candidates,
    register_falsifier,
    registered_falsifiers,
    unregister_falsifier,
    verdicts_of,
    would,
)
from tap_grid.models import Batch, BatchEvent, Entity
from tap_grid.tests.test_reconcile_candidates import CONTAINS, TARGET, Graph, _run, _surface

T0 = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.grid_fixtures.models import ConstrainedSource

    monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (CONTAINS,), raising=False)


@pytest.fixture(autouse=True)
def clean_registry() -> Any:
    """Every case starts with no falsifier registered for the fixture type and leaves none."""
    unregister_falsifier(TARGET)
    yield
    unregister_falsifier(TARGET)


def _candidate(eid: uuid.UUID | None = None, *, interval_first: datetime | None = T0) -> Candidate:
    return Candidate(
        entity_id=eid or uuid.uuid4(),
        entity_type=TARGET,
        reason="dropped_from_observation",
        surface=0,
        relation="source.targets",
        subject="P",
        edge_type=CONTAINS,
        parent=uuid.uuid4(),
        interval_first=interval_first,
    )


# ---------------------------------------------------------------------------
# The table: identity and owner decide, never HTTP status
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-reconcile-falsifier-7")
@pytest.mark.spec("req-grid-reconcile-falsifier-8")
class TestClassification:
    HELD = Expected(source_id="R123", owner="acme", name="widgets")

    def test_same_identity_same_owner_new_name_is_a_rename(self) -> None:
        got = classify(self.HELD, Probe("found", "R123", "acme", "gadgets"), interval_first=T0)
        assert got == {"verdict": RELOCATED, "kind": RELOCATED_RENAMED}

    def test_same_identity_different_owner_is_a_transfer(self) -> None:
        got = classify(self.HELD, Probe("found", "R123", "other-org", "widgets"), interval_first=T0)
        assert got == {"verdict": RELOCATED, "kind": RELOCATED_TRANSFERRED}

    def test_a_different_identity_at_the_address_is_reidentified(self) -> None:
        got = classify(self.HELD, Probe("found", "R999", "acme", "widgets"), interval_first=T0)
        assert got == {"verdict": REIDENTIFIED}

    def test_same_identity_same_owner_is_present_at_probe(self) -> None:
        got = classify(self.HELD, Probe("found", "R123", "acme", "widgets"), interval_first=T0)
        assert got["verdict"] == PRESENT_AT_PROBE

    def test_not_found_is_dropped(self) -> None:
        assert classify(self.HELD, Probe("not_found"), interval_first=T0) == {"verdict": DROPPED_FROM_OBSERVATION}

    @pytest.mark.parametrize("reason", sorted(UNDETERMINED_REASONS))
    def test_every_failure_to_answer_is_undetermined_with_its_reason(self, reason: str) -> None:
        assert classify(self.HELD, Probe(reason), interval_first=T0) == {"verdict": UNDETERMINED, "reason": reason}  # type: ignore[arg-type]

    def test_http_success_with_no_name_on_either_side_is_still_presence(self) -> None:
        held = Expected(source_id="R123", owner="acme")
        assert classify(held, Probe("found", "R123", "acme"), interval_first=T0)["verdict"] == PRESENT_AT_PROBE

    def test_an_unknown_probe_status_is_refused(self) -> None:
        with pytest.raises(FalsifierError) as excinfo:
            classify(self.HELD, Probe("maybe"), interval_first=T0)  # type: ignore[arg-type]
        assert excinfo.value.code == "bad_verdict"

    def test_would_names_one_home_per_verdict(self) -> None:
        eid = uuid.uuid4()
        assert would(Verdict(eid, DROPPED_FROM_OBSERVATION)) == {"write": "tombstone", "home": "entity"}
        assert would(Verdict(eid, RELOCATED, kind=RELOCATED_RENAMED)) == {"write": "rename", "home": "entity_name"}
        assert would(Verdict(eid, RELOCATED, kind=RELOCATED_TRANSFERRED)) == {
            "write": "end_ownership_edge",
            "home": "ownership_edge",
        }
        for verdict in (PRESENT_AT_PROBE, UNDETERMINED, REIDENTIFIED):
            kw = {"cause": CAUSE_INDETERMINATE} if verdict == PRESENT_AT_PROBE else {}
            kw = {"reason": "budget"} if verdict == UNDETERMINED else kw
            assert would(Verdict(eid, verdict, **kw)) == {"write": "none", "home": "run_record"}  # type: ignore[arg-type]


@pytest.mark.spec("req-grid-reconcile-falsifier-4")
class TestPresentAtProbeClaimsNoDefect:
    HELD = Expected(source_id="R123", owner="acme", name="widgets")

    def test_created_at_or_after_the_interval_start_rules_timing_in(self) -> None:
        for created in (T0, T0 + timedelta(seconds=1)):
            got = classify(self.HELD, Probe("found", "R123", "acme", "widgets", created_at=created), interval_first=T0)
            assert got == {"verdict": PRESENT_AT_PROBE, "cause": CAUSE_CREATED_AFTER}

    def test_created_before_the_interval_start_rules_nothing_out(self) -> None:
        got = classify(
            self.HELD, Probe("found", "R123", "acme", "widgets", created_at=T0 - timedelta(days=1)), interval_first=T0
        )
        assert got == {"verdict": PRESENT_AT_PROBE, "cause": CAUSE_INDETERMINATE}

    def test_no_creation_time_or_no_interval_is_indeterminate(self) -> None:
        assert (
            classify(self.HELD, Probe("found", "R123", "acme", "widgets"), interval_first=T0)["cause"]
            == CAUSE_INDETERMINATE
        )
        assert (
            classify(self.HELD, Probe("found", "R123", "acme", "widgets", created_at=T0), interval_first=None)["cause"]
            == CAUSE_INDETERMINATE
        )

    def test_the_statement_is_the_disjunction_and_never_a_defect_claim(self) -> None:
        assert "created after the listing started" in PRESENT_STATEMENT
        assert "access to it was restored" in PRESENT_STATEMENT
        assert "defect" not in PRESENT_STATEMENT and "missed" not in PRESENT_STATEMENT


class TestTheVerdictType:
    def test_the_five_verdicts_and_their_qualifiers_are_closed(self) -> None:
        eid = uuid.uuid4()
        assert VERDICTS == {DROPPED_FROM_OBSERVATION, PRESENT_AT_PROBE, RELOCATED, UNDETERMINED, REIDENTIFIED}
        with pytest.raises(FalsifierError):
            Verdict(eid, "GONE")
        with pytest.raises(FalsifierError):
            Verdict(eid, UNDETERMINED, reason="unlucky")
        with pytest.raises(FalsifierError):
            Verdict(eid, RELOCATED, kind="moved")
        with pytest.raises(FalsifierError):
            Verdict(eid, PRESENT_AT_PROBE, cause="collector_defect")

    def test_registration_is_once_per_type(self) -> None:
        falsifier = FakeSourceFalsifier(FakeSource())
        register_falsifier(TARGET, falsifier)
        assert registered_falsifiers()[TARGET] is falsifier and falsifier.entity_type == TARGET
        with pytest.raises(ImproperlyConfigured):
            register_falsifier(TARGET, FakeSourceFalsifier(FakeSource()))
        with pytest.raises(ImproperlyConfigured):
            register_falsifier("other", object())  # type: ignore[arg-type]

    def test_the_base_class_defaults_batch_to_singular(self) -> None:
        class One(Falsifier):
            def falsify_one(self, candidate: Candidate, context: FalsifyContext) -> Verdict:
                return Verdict(candidate.entity_id, DROPPED_FROM_OBSERVATION)

        cands = [_candidate(), _candidate()]
        got = One().batch_falsify(cands, FalsifyContext("b", None))
        assert [v.entity_id for v in got] == [c.entity_id for c in cands]
        with pytest.raises(NotImplementedError):
            Falsifier().batch_falsify(cands, FalsifyContext("b", None))


# ---------------------------------------------------------------------------
# The four proof cases, against the fake source (-6)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-reconcile-falsifier-6")
class TestFourProofCases:
    def test_the_reference_falsifier_passes_the_four_cases_in_one_call(self) -> None:
        source = FakeSource()
        cands = {case: _candidate() for case in FOUR_CASES}
        for case, c in cands.items():
            source.holds(c.entity_id, f"src-{case}", owner="acme", name=case)
        source.present(cands["present"].entity_id, created_at=T0 + timedelta(minutes=1))
        source.dropped(cands["dropped"].entity_id)
        source.forbidden(cands["forbidden"].entity_id)
        source.reidentified(cands["reidentified"].entity_id, "src-new")

        by_case = run_four_cases(FakeSourceFalsifier(source), cands, FalsifyContext("b", None))

        assert source.calls == 1, "one aliased probe for the batch, not one per candidate"
        assert by_case["present"].cause == CAUSE_CREATED_AFTER
        assert by_case["forbidden"].probe == {
            "status": "forbidden",
            "source_id": None,
            "owner": None,
            "name": None,
            "created_at": None,
            "detail": "403",
        }

    def test_the_harness_fails_on_a_wrong_verdict(self) -> None:
        class AlwaysDropped(Falsifier):
            def falsify_one(self, candidate: Candidate, context: FalsifyContext) -> Verdict:
                return Verdict(candidate.entity_id, DROPPED_FROM_OBSERVATION)

        cands = {case: _candidate() for case in FOUR_CASES}
        with pytest.raises(AssertionError, match="present: expected PRESENT_AT_PROBE"):
            run_four_cases(AlwaysDropped(), cands, FalsifyContext("b", None))
        with pytest.raises(AssertionError, match="missing"):
            run_four_cases(AlwaysDropped(), {"present": cands["present"]}, FalsifyContext("b", None))


# ---------------------------------------------------------------------------
# The dispatch on a real run: record, retire nothing
# ---------------------------------------------------------------------------


def _snapshot() -> dict[uuid.UUID, tuple[bool, int, str]]:
    """Every node and edge but the run batches themselves: writing the record on the run's own
    Batch row bumps that row, as recording the statement and the candidates already do."""
    return {e.pk: (e.deleted_at is not None, e.version, e.name) for e in Entity.objects.exclude(entity_type="batch")}


def _events() -> int:
    return BatchEvent.objects.count()


@pytest.fixture
def graph() -> Graph:
    return Graph()


@pytest.mark.django_db
class TestDispatch:
    def _run_with_candidates(self, graph: Graph) -> Batch:
        """P's surface complete; c1, c2 observed → c3 is the candidate."""
        write = graph.observe(graph.p, graph.c[0], graph.c[1])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record_candidates(run, produced_batches=[str(write.entity_id)])
        run.refresh_from_db()
        return run

    @pytest.mark.spec("req-grid-reconcile-falsifier-1")
    def test_no_falsifier_means_not_reconcilable_and_nothing_probed(self, graph: Graph) -> None:
        run = self._run_with_candidates(graph)
        before, events = _snapshot(), _events()

        record = falsify_candidates(run)

        [entry] = record["entries"]
        assert entry["entity_id"] == str(graph.c[2].pk) and entry["entity_type"] == TARGET
        assert entry["outcome"] == NOT_RECONCILABLE and entry["verdict"] is None and entry["probe"] is None
        assert entry["would"] == {"write": "none", "home": "run_record"}
        assert record["not_reconcilable"] == [TARGET] and record["calls"] == {} and record["authority"] == "off"
        assert _snapshot() == before and _events() == events, "nothing retired, bumped, renamed or recorded as an event"
        run.refresh_from_db()
        assert verdicts_of(run) == record
        summary = batch_summary(run.entity_id, with_counts=False)
        assert summary is not None and summary["verdicts"] == record

    @pytest.mark.spec("req-grid-reconcile-falsifier-1")
    @pytest.mark.spec("req-grid-reconcile-falsifier-3")
    def test_a_registered_falsifier_judges_and_the_record_names_the_write_it_would_make(self, graph: Graph) -> None:
        run = self._run_with_candidates(graph)
        source = FakeSource()
        source.holds(graph.c[2].pk, "src-c3", owner="P", name="c3")
        source.dropped(graph.c[2].pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before, events = _snapshot(), _events()

        record = falsify_candidates(run)

        [entry] = record["entries"]
        assert entry["outcome"] == JUDGED and entry["verdict"] == DROPPED_FROM_OBSERVATION
        assert entry["would"] == {"write": "tombstone", "home": "entity"}
        assert entry["probe"]["status"] == "not_found" and entry["surface"] == 0
        assert entry["candidate_reason"] == "dropped_from_observation"
        assert record["calls"] == {TARGET: 1} and record["not_reconcilable"] == []
        assert _snapshot() == before and _events() == events, "a DROPPED verdict retires nothing with authority off"
        assert not Entity.objects.get(pk=graph.c[2].pk).deleted_at

    @pytest.mark.spec("req-grid-reconcile-falsifier-4")
    def test_present_at_probe_is_recorded_with_the_disjunction_and_a_cause(self, graph: Graph) -> None:
        run = self._run_with_candidates(graph)
        [candidate] = candidates_from(run)
        assert candidate.interval_first is not None, "this run's surface carries its interval start"
        source = FakeSource()
        source.holds(graph.c[2].pk, "src-c3", owner="P", name="c3")
        source.present(graph.c[2].pk, created_at=candidate.interval_first + timedelta(seconds=5))
        register_falsifier(TARGET, FakeSourceFalsifier(source))

        [entry] = falsify_candidates(run)["entries"]

        assert entry["verdict"] == PRESENT_AT_PROBE and entry["cause"] == CAUSE_CREATED_AFTER
        assert entry["statement"] == PRESENT_STATEMENT and "defect" not in entry["statement"]
        assert entry["would"] == {"write": "none", "home": "run_record"}

    @pytest.mark.spec("req-grid-reconcile-falsifier-7")
    @pytest.mark.spec("req-grid-reconcile-falsifier-9")
    def test_a_transfer_would_end_the_ownership_edge_only(self, graph: Graph) -> None:
        run = self._run_with_candidates(graph)
        source = FakeSource()
        source.holds(graph.c[2].pk, "src-c3", owner="P", name="c3")
        source.transferred(graph.c[2].pk, "someone-else")
        register_falsifier(TARGET, FakeSourceFalsifier(source))
        before = _snapshot()

        [entry] = falsify_candidates(run)["entries"]

        assert entry["verdict"] == RELOCATED and entry["kind"] == RELOCATED_TRANSFERRED
        assert entry["would"] == {"write": "end_ownership_edge", "home": "ownership_edge"}
        assert _snapshot() == before

    def test_one_call_per_type_for_many_candidates(self, graph: Graph) -> None:
        from tap_grid.services import create_edge
        from tap_grid.tests.test_reconcile_candidates import _node, batch

        with batch("test.falsifier.more"):
            extra = [_node(TARGET, f"x{i}") for i in range(47)]
            for child in extra:
                create_edge(graph.p, child, CONTAINS)
        run = self._run_with_candidates(graph)
        source = FakeSource()
        for c in [graph.c[2], *extra]:
            source.holds(c.pk, f"src-{c.name}", owner="P", name=c.name)
            source.dropped(c.pk)
        register_falsifier(TARGET, FakeSourceFalsifier(source))

        record = falsify_candidates(run)

        assert record["candidates"] == 48 and source.calls == 1 and record["calls"] == {TARGET: 1}
        assert [e["entity_id"] for e in record["entries"]] == sorted(e["entity_id"] for e in record["entries"])

    def test_a_falsifier_that_raises_or_forgets_a_candidate_is_undetermined_errored(self, graph: Graph) -> None:
        class Broken(Falsifier):
            def batch_falsify(self, candidates: Any, context: FalsifyContext) -> list[Verdict]:
                raise RuntimeError("probe exploded")

        run = self._run_with_candidates(graph)
        register_falsifier(TARGET, Broken())
        before = _snapshot()
        [entry] = falsify_candidates(run)["entries"]
        assert entry["outcome"] == JUDGED and entry["verdict"] == UNDETERMINED and entry["reason"] == "errored"
        assert "probe exploded" in entry["note"] and entry["probe"] is None
        assert _snapshot() == before

        class Forgetful(Falsifier):
            def batch_falsify(self, candidates: Any, context: FalsifyContext) -> list[Verdict]:
                return []

        unregister_falsifier(TARGET)
        register_falsifier(TARGET, Forgetful())
        [entry] = falsify_candidates(run)["entries"]
        assert entry["verdict"] == UNDETERMINED and entry["reason"] == "errored" and "no verdict" in entry["note"]

    def test_refusals_write_nothing(self, graph: Graph) -> None:
        run = _run(_surface(graph.p))
        with pytest.raises(FalsifierError) as excinfo:
            falsify_candidates(run)
        assert excinfo.value.code == "no_candidates"
        run.refresh_from_db()
        assert verdicts_of(run) is None

        run = close_batch(self._run_with_candidates(graph))
        with pytest.raises(FalsifierError) as excinfo:
            falsify_candidates(run)
        assert excinfo.value.code == "batch_not_open"
        run.refresh_from_db()
        assert verdicts_of(run) is None

    def test_the_context_carries_the_statement_and_extras(self, graph: Graph) -> None:
        seen: list[FalsifyContext] = []

        class Peek(Falsifier):
            def batch_falsify(self, candidates: Any, context: FalsifyContext) -> list[Verdict]:
                seen.append(context)
                return [Verdict(c.entity_id, UNDETERMINED, reason="budget") for c in candidates]

        run = self._run_with_candidates(graph)
        register_falsifier(TARGET, Peek())
        falsify_candidates(run, extra={"credential": "scope:key"})
        [context] = seen
        assert context.batch_id == str(run.entity_id) and context.extra == {"credential": "scope:key"}
        assert context.statement is not None and context.statement["surfaces"][0]["subject"] == str(graph.p.pk)
