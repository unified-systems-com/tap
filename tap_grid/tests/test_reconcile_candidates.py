"""Candidate derivation (``req-grid-reconcile-candidates``, phase 4 slice 2, Issue# 596 - tap).

Fan-out from the parent through its declared containment edge type, minus what this run's
committed batches touched; the prerequisite read per parent; a retired parent yields
nothing; withdrawal is a distinct outcome with its own reason; a reference relation never
yields a candidate. Authority is off: the record is derived and stored, nothing is retired.

The fixture graph uses ``grid_fixtures``' constrained types with containment declared per
test by monkeypatch (as ``test_delete_cascade`` does). Nodes and edges are written through
the service layer under explicit batches, so "observed by this run" is exactly the
BatchEvents those batches recorded — the same record a collector's GRIFT import leaves.
The batch lifecycle helpers are the intentional below-service-layer setup: the statement and
the record are bookkeeping ON a batch.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tap_grid.batch import batch_summary, close_batch, create_batch, fail_batch
from tap_grid.candidates import (
    ABSENT,
    METADATA_KEY,
    WITHDRAWN,
    CandidatesError,
    candidates_of,
    derive_candidates,
    record_candidates,
)
from tap_grid.completeness import record_completeness
from tap_grid.context import set_batch_id
from tap_grid.models import Batch, Entity
from tap_grid.service_types import DELETE_REASONS
from tap_grid.services import create_edge, create_node, delete_node, patch_node

SOURCE = "grid_fixtures__constrained_source"
TARGET = "grid_fixtures__constrained_target"
CONTAINS = "CONSTRAINED_LINK__grid_fixtures"  # declared containment in these tests
REFERS = "ALT_LINK__grid_fixtures"  # left as a reference


@pytest.fixture(autouse=True)
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.grid_fixtures.models import ConstrainedSource

    monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (CONTAINS,), raising=False)


@contextmanager
def batch(source: str) -> Iterator[Batch]:
    """Scope service writes to one explicit batch, closing it on the way out."""
    b = create_batch(source=source)
    set_batch_id(str(b.entity_id))
    try:
        yield b
    finally:
        set_batch_id(None)
    close_batch(b)


def _node(entity_type: str, name: str) -> Entity:
    result = create_node(entity_type, {"name": name})
    assert result.success, result.errors
    assert result.entity_id is not None
    return Entity.objects.get(pk=result.entity_id)


def _observe(*entities: Entity) -> None:
    """Re-observe nodes the way a collector's upsert does: a write, changed or not."""
    for entity in entities:
        result = patch_node(entity.pk, {"name": entity.name})
        assert result.success, result.errors


def _surface(parent: Entity, **overrides: Any) -> dict[str, Any]:
    now = timezone.now().isoformat()
    base: dict[str, Any] = {
        "relation": "source.targets",
        "edge_type": CONTAINS,
        "filter": None,
        "subject": str(parent.pk),
        "interval": {"first": now, "last": now},
        "scope_authorized": True,
        "enumeration_complete": True,
        "source_consistent": "unknown",
        "source_promise": None,
        "filter_control": None,
        "count_observed": None,
        "count_reported": None,
        "admitted": True,
        "applied_batches": [],
        "reasons": {"source_consistent": "fixture source makes no snapshot promise"},
    }
    base.update(overrides)
    return base


def _run(*surfaces: dict[str, Any]) -> Batch:
    """A run's lifecycle batch carrying a completeness statement, still open."""
    run = create_batch(source="test.candidates.run")
    record_completeness(run, list(surfaces))
    run.refresh_from_db()
    return run


def _ids(entry: dict[str, Any]) -> set[str]:
    return {c["entity_id"] for c in entry["candidates"]}


class Graph:
    """P contains c1..c3 and refers to r; Q contains q1, q2. Seeded in one committed batch."""

    def __init__(self) -> None:
        with batch("test.candidates.seed") as seed:
            self.p = _node(SOURCE, "P")
            self.q = _node(SOURCE, "Q")
            self.c = [_node(TARGET, f"c{i}") for i in (1, 2, 3)]
            self.r = _node(TARGET, "r")
            self.qs = [_node(TARGET, f"q{i}") for i in (1, 2)]
            for child in self.c:
                create_edge(self.p, child, CONTAINS)
            create_edge(self.p, self.r, REFERS)
            for child in self.qs:
                create_edge(self.q, child, CONTAINS)
        self.seed = seed

    def observe(self, *entities: Entity) -> Batch:
        """This run's write batch: the nodes it saw, committed."""
        with batch("test.candidates.write") as write:
            _observe(*entities)
        return write


@pytest.fixture
def graph() -> Graph:
    return Graph()


# ---------------------------------------------------------------------------
# req-grid-reconcile-candidates-1 — fan-out derivation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFanOutDerivation:
    @pytest.mark.spec("req-grid-reconcile-candidates-1")
    def test_children_minus_observed_are_the_candidates(self, graph: Graph) -> None:
        write = graph.observe(graph.p, graph.c[0], graph.c[1])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))

        record = record_candidates(run, produced_batches=[str(write.entity_id)])

        [entry] = record["surfaces"]
        assert entry["outcome"] == "derived" and entry["reason"] is None
        assert entry["parent"] == str(graph.p.pk)
        assert (entry["children"], entry["observed"]) == (3, 2)
        assert _ids(entry) == {str(graph.c[2].pk)}, "c3 was not observed this run; c1 and c2 were"
        [candidate] = entry["candidates"]
        assert candidate["entity_type"] == TARGET and candidate["reason"] == ABSENT
        assert record["authority"] == "off"
        assert record["observed_batches"] == [str(write.entity_id)]
        run.refresh_from_db()
        assert candidates_of(run) == record
        assert all(Entity.objects.get(pk=c.pk).deleted_at is None for c in graph.c), "nothing is retired"

    @pytest.mark.spec("req-grid-reconcile-candidates-1")
    def test_no_per_node_stamp_is_read(self, graph: Graph) -> None:
        """The derivation reads the topology and the run's batches — never a typed row."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource, ConstrainedTarget

        write = graph.observe(graph.p, graph.c[0], graph.c[1])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        with CaptureQueriesContext(connection) as captured:
            derive_candidates(run, produced_batches=[str(write.entity_id)])
        sql = "\n".join(q["sql"] for q in captured.captured_queries)
        assert captured.captured_queries, "the derivation reads the grid"
        for model in (ConstrainedSource, ConstrainedTarget):
            assert model._meta.db_table not in sql, f"a typed row of {model.__name__} was read"
        assert "flip_map" not in sql

    @pytest.mark.spec("req-grid-reconcile-candidates-1")
    def test_an_unchanged_re_observation_still_counts_as_observed(self, graph: Graph) -> None:
        """A no-op upsert is an observation (req-grid-reconcile-evidence-7): the batch's event is the record."""
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["outcome"] == "derived" and entry["candidates"] == []
        assert entry["observed"] == 3

    @pytest.mark.spec("req-grid-reconcile-candidates-1")
    def test_a_failed_write_batch_is_not_an_observation(self, graph: Graph) -> None:
        """Every child is unobserved when the run's only batch did not commit — but so is P."""
        write = create_batch(source="test.candidates.write")
        set_batch_id(str(write.entity_id))
        try:
            _observe(graph.p, *graph.c)
        finally:
            set_batch_id(None)
        fail_batch(write, "boom")
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record = derive_candidates(run, produced_batches=[str(write.entity_id)])
        assert record["observed_batches"] == []
        [entry] = record["surfaces"]
        assert entry["outcome"] == "skipped" and entry["reason"].startswith("parent_not_observed")
        assert entry["candidates"] == []

    def test_a_retired_child_is_not_a_child(self, graph: Graph) -> None:
        assert delete_node(graph.c[2].pk, reason="operator").success
        write = graph.observe(graph.p, graph.c[0])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["children"] == 2
        assert _ids(entry) == {str(graph.c[1].pk)}


# ---------------------------------------------------------------------------
# req-grid-reconcile-candidates-2 — prerequisite per parent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPrerequisitePerParent:
    @pytest.mark.spec("req-grid-reconcile-candidates-2")
    def test_a_failed_sibling_listing_does_not_veto_this_parent(self, graph: Graph) -> None:
        """Q's listing failed; P's own surface completed: P's children are judged, Q's are not."""
        write = graph.observe(graph.p, graph.q, graph.c[0])
        run = _run(
            _surface(graph.p, applied_batches=[str(write.entity_id)]),
            _surface(
                graph.q,
                enumeration_complete=False,
                applied_batches=[str(write.entity_id)],
                reasons={
                    "source_consistent": "fixture source makes no snapshot promise",
                    "enumeration_complete": "listing failed: HTTP 502 on page 2",
                },
            ),
        )
        p_entry, q_entry = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert p_entry["outcome"] == "derived"
        assert _ids(p_entry) == {str(graph.c[1].pk), str(graph.c[2].pk)}
        assert q_entry["outcome"] == "skipped"
        assert q_entry["reason"].startswith("surface_not_reconcilable")
        assert "listing failed" in q_entry["reason"]
        assert q_entry["candidates"] == [], "q1 and q2 were not observed either, and are still not candidates"

    @pytest.mark.spec("req-grid-reconcile-candidates-2")
    def test_a_parent_the_run_did_not_observe_has_no_candidates(self, graph: Graph) -> None:
        """A complete-looking surface for a parent this run never wrote proves nothing about its children."""
        write = graph.observe(graph.c[0])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["outcome"] == "skipped" and entry["reason"].startswith("parent_not_observed")
        assert entry["candidates"] == []

    @pytest.mark.spec("req-grid-reconcile-candidates-2")
    def test_an_absent_sibling_surface_is_not_consulted(self, graph: Graph) -> None:
        write = graph.observe(graph.p, graph.c[0], graph.c[1], graph.c[2])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["outcome"] == "derived" and entry["candidates"] == []


# ---------------------------------------------------------------------------
# req-grid-reconcile-candidates-3 — ordering preserved
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrderingPreserved:
    @pytest.mark.spec("req-grid-reconcile-candidates-3")
    def test_a_retired_parent_yields_no_candidates(self, graph: Graph) -> None:
        """P is gone: its children belong to cascade, whatever the surface says."""
        write = graph.observe(graph.p, graph.c[0])
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        assert delete_node(graph.p.pk, reason="operator").success
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["outcome"] == "skipped"
        assert entry["reason"].startswith("parent_retired")
        assert entry["parent"] == str(graph.p.pk)
        assert entry["candidates"] == [] and entry["children"] is None

    @pytest.mark.spec("req-grid-reconcile-candidates-3")
    def test_a_retired_parent_is_not_withdrawn_either(self, graph: Graph) -> None:
        previous = _run(_surface(graph.q, applied_batches=[str(graph.seed.entity_id)]))
        close_batch(previous)
        assert delete_node(graph.q.pk, reason="operator").success
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record = derive_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(graph.seed.entity_id)],
        )
        _, q_entry = record["surfaces"]
        assert q_entry["outcome"] == "skipped" and q_entry["reason"].startswith("parent_retired")


# ---------------------------------------------------------------------------
# req-grid-reconcile-candidates-4 — withdrawal distinguished
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWithdrawalDistinguished:
    def _previous(self, graph: Graph) -> Batch:
        """The previous run's lifecycle batch: P and Q both in scope, observed via the seed batch."""
        previous = _run(
            _surface(graph.p, applied_batches=[str(graph.seed.entity_id)]),
            _surface(graph.q, applied_batches=[str(graph.seed.entity_id)]),
        )
        return close_batch(previous)

    @pytest.mark.spec("req-grid-reconcile-candidates-4")
    def test_a_previously_observed_child_now_out_of_scope_is_withdrawn(self, graph: Graph) -> None:
        previous = self._previous(graph)
        # A node an operator hung under Q after the previous run: nobody ever observed it.
        with batch("test.candidates.operator"):
            stray = _node(TARGET, "q-stray")
            create_edge(graph.q, stray, CONTAINS)
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))  # Q is no longer in scope

        record = record_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(graph.seed.entity_id)],
        )

        assert record["previous"] == {
            "batch": str(previous.entity_id),
            "compared": True,
            "reason": None,
            "observed_batches": [str(graph.seed.entity_id)],
        }
        p_entry, q_entry = record["surfaces"]
        assert p_entry["outcome"] == "derived" and p_entry["candidates"] == []
        assert q_entry["outcome"] == "withdrawn"
        assert q_entry["reason"].startswith("scope_withdrawn")
        assert q_entry["parent"] == str(graph.q.pk)
        assert (q_entry["children"], q_entry["observed"]) == (3, 2)
        assert _ids(q_entry) == {str(q.pk) for q in graph.qs}, "q1 and q2 were observed under the withdrawn scope"
        assert str(stray.pk) not in _ids(q_entry), "a never-observed out-of-scope node is nothing"
        assert {c["reason"] for c in q_entry["candidates"]} == {WITHDRAWN}
        assert all(Entity.objects.get(pk=q.pk).deleted_at is None for q in graph.qs), "nothing is retired"

    @pytest.mark.spec("req-grid-reconcile-candidates-4")
    def test_scope_refused_this_run_is_a_withdrawal_not_an_absence(self, graph: Graph) -> None:
        """This run's statement still names Q, but the credential could no longer ask."""
        previous = self._previous(graph)
        write = graph.observe(graph.p, *graph.c)
        run = _run(
            _surface(graph.p, applied_batches=[str(write.entity_id)]),
            _surface(
                graph.q,
                scope_authorized=False,
                reasons={
                    "source_consistent": "fixture source makes no snapshot promise",
                    "scope_authorized": "credential lost read on Q",
                },
            ),
        )
        record = derive_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(graph.seed.entity_id)],
        )
        by_outcome = {e["outcome"]: e for e in record["surfaces"] if e["subject"] == str(graph.q.pk)}
        assert by_outcome["skipped"]["candidates"] == [], "absence from a refused surface claims nothing"
        assert _ids(by_outcome["withdrawn"]) == {str(q.pk) for q in graph.qs}

    @pytest.mark.spec("req-grid-reconcile-candidates-4")
    def test_without_a_previous_run_withdrawal_is_not_observable(self, graph: Graph) -> None:
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record = derive_candidates(run, produced_batches=[str(write.entity_id)])
        assert record["previous"] is None
        assert [e["outcome"] for e in record["surfaces"]] == ["derived"]

    @pytest.mark.spec("req-grid-reconcile-candidates-4")
    def test_a_previous_run_without_a_statement_compares_nothing(self, graph: Graph) -> None:
        previous = close_batch(create_batch(source="test.candidates.run"))
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record = derive_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(graph.seed.entity_id)],
        )
        assert record["previous"]["compared"] is False
        assert record["previous"]["reason"].startswith("no_statement")
        assert [e["outcome"] for e in record["surfaces"]] == ["derived"]

    @pytest.mark.spec("req-grid-reconcile-candidates-4")
    def test_a_surface_still_in_scope_is_not_withdrawn(self, graph: Graph) -> None:
        previous = self._previous(graph)
        write = graph.observe(graph.p, graph.q, *graph.c, *graph.qs)
        run = _run(
            _surface(graph.p, applied_batches=[str(write.entity_id)]),
            _surface(graph.q, applied_batches=[str(write.entity_id)]),
        )
        record = derive_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(graph.seed.entity_id)],
        )
        assert [e["outcome"] for e in record["surfaces"]] == ["derived", "derived"]


# ---------------------------------------------------------------------------
# req-grid-reconcile-candidates-5 — references excluded
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReferencesExcluded:
    @pytest.mark.spec("req-grid-reconcile-candidates-5")
    def test_a_node_reached_only_by_a_reference_is_never_a_candidate(self, graph: Graph) -> None:
        """r hangs off P by ALT_LINK and was not observed; it is not P's child for derivation."""
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["children"] == 3
        assert str(graph.r.pk) not in _ids(entry) and entry["candidates"] == []

    @pytest.mark.spec("req-grid-reconcile-candidates-5")
    def test_a_surface_mapped_to_a_reference_relation_yields_nothing(self, graph: Graph) -> None:
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, relation="source.alts", edge_type=REFERS, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["outcome"] == "skipped"
        assert entry["reason"].startswith("relation_not_containment")
        assert entry["candidates"] == [], "r is unobserved, and still not a candidate"

    @pytest.mark.spec("req-grid-reconcile-candidates-5")
    def test_a_reference_relation_is_not_withdrawn_either(self, graph: Graph) -> None:
        previous = close_batch(
            _run(
                _surface(graph.p, relation="source.alts", edge_type=REFERS, applied_batches=[str(graph.seed.entity_id)])
            )
        )
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record = derive_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(graph.seed.entity_id)],
        )
        _, alt_entry = record["surfaces"]
        assert alt_entry["outcome"] == "skipped" and alt_entry["reason"].startswith("relation_not_containment")

    @pytest.mark.spec("req-grid-reconcile-candidates-5")
    def test_an_unmapped_surface_yields_nothing(self, graph: Graph) -> None:
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, edge_type=None, applied_batches=[str(write.entity_id)]))
        [entry] = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert entry["outcome"] == "skipped" and entry["reason"].startswith("relation_unmapped")


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRecord:
    def test_candidate_reasons_are_the_closed_delete_vocabulary(self) -> None:
        from tap_grid.candidates import _SCHEMA

        allowed = set(_SCHEMA["$defs"]["surface"]["properties"]["candidates"]["items"]["properties"]["reason"]["enum"])
        assert allowed == {ABSENT, WITHDRAWN}
        assert allowed <= DELETE_REASONS

    def test_nothing_recorded_is_none(self) -> None:
        run = create_batch(source="test")
        assert candidates_of(run) is None
        summary = batch_summary(run.entity_id, with_counts=False)
        assert summary is not None and summary["candidates"] is None

    def test_a_run_without_a_statement_has_nothing_to_derive_from(self) -> None:
        run = create_batch(source="test")
        with pytest.raises(CandidatesError) as excinfo:
            derive_candidates(run, produced_batches=[])
        assert excinfo.value.code == "no_statement"
        run.refresh_from_db()
        assert candidates_of(run) is None

    def test_only_an_open_batch_takes_a_record(self, graph: Graph) -> None:
        run = close_batch(_run(_surface(graph.p)))
        with pytest.raises(CandidatesError) as excinfo:
            record_candidates(run, produced_batches=[])
        assert excinfo.value.code == "batch_not_open"

    def test_a_zero_surface_statement_records_an_empty_derivation(self) -> None:
        run = _run()
        record = record_candidates(run, produced_batches=[])
        assert record["surfaces"] == [] and record["observed_batches"] == []
        summary = batch_summary(run.entity_id, with_counts=False)
        assert summary is not None and summary["candidates"] == record

    def test_subjects_that_are_not_grid_ids_are_skipped_not_guessed(self, graph: Graph) -> None:
        write = graph.observe(graph.p)
        run = _run(
            _surface(graph.p, subject="repo:unified-systems-com/tap", applied_batches=[str(write.entity_id)]),
            _surface(graph.p, subject=str(uuid.uuid4()), applied_batches=[str(write.entity_id)]),
        )
        locator, unknown = derive_candidates(run, produced_batches=[str(write.entity_id)])["surfaces"]
        assert locator["reason"].startswith("subject_unresolved") and locator["parent"] is None
        assert unknown["reason"].startswith("parent_unknown")

    def test_the_record_sits_beside_the_statement(self, graph: Graph) -> None:
        write = graph.observe(graph.p, *graph.c)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        record_candidates(run, produced_batches=[str(write.entity_id)])
        run.refresh_from_db()
        assert set(run.metadata) >= {"completeness", METADATA_KEY}


NEST = "NESTING_LINK__grid_fixtures"  # containment declared on the TARGET type in these tests


@pytest.mark.django_db
@pytest.mark.spec("req-grid-reconcile-candidates-6")
class TestContradiction:
    """A candidate whose contained closure holds a node this run observed live (Issue# 656 - tap)."""

    @pytest.fixture(autouse=True)
    def nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        monkeypatch.setattr(ConstrainedTarget, "CONTAINMENT_EDGES", (NEST,), raising=False)

    @staticmethod
    def _grandchild(under: Entity, name: str = "g") -> Entity:
        with batch("test.candidates.grandchild"):
            g = _node(TARGET, name)
            create_edge(under, g, NEST)
        return g

    def _derive(self, graph: Graph, *observed: Entity) -> dict[str, Any]:
        write = graph.observe(graph.p, *observed)
        run = _run(_surface(graph.p, applied_batches=[str(write.entity_id)]))
        return derive_candidates(run, produced_batches=[str(write.entity_id)])

    def test_an_observed_descendant_makes_the_candidate_a_contradiction(
        self, graph: Graph, caplog: pytest.LogCaptureFixture
    ) -> None:
        """P → c3 → g; the run observed g and not c3: c3 is a candidate AND its closure holds
        live evidence. Recorded on the candidate, exactly, with the descendant named."""
        g = self._grandchild(graph.c[2])
        with caplog.at_level("WARNING", logger="tap_grid.candidates"):
            record = self._derive(graph, graph.c[0], graph.c[1], g)
        [c3] = record["surfaces"][0]["candidates"]
        assert c3["entity_id"] == str(graph.c[2].pk)
        assert c3["contradiction"] == {"kind": "observed_descendants", "observed_descendants": [str(g.pk)], "count": 1}
        assert any("[265c]" in r.getMessage() and str(g.pk) in r.getMessage() for r in caplog.records)

    def test_no_observed_descendant_means_no_contradiction(self, graph: Graph) -> None:
        self._grandchild(graph.c[2])
        record = self._derive(graph, graph.c[0], graph.c[1])
        [c3] = record["surfaces"][0]["candidates"]
        assert c3["contradiction"] is None
        # and a leaf candidate (no containment declared on its type) never walks at all
        record = self._derive(graph, graph.c[2])
        assert all(c["contradiction"] is None for c in record["surfaces"][0]["candidates"])

    def test_a_closure_over_the_cap_is_a_contradiction_of_its_own_kind(
        self, graph: Graph, settings: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown is refused, never passed: with the cascade cap below the closure, the candidate
        is recorded closure_unknown even though nothing under it was observed."""
        self._grandchild(graph.c[2])
        settings.TAP_CASCADE_MAX_CLOSURE = 0
        with caplog.at_level("WARNING", logger="tap_grid.candidates"):
            record = self._derive(graph, graph.c[0], graph.c[1])
        [c3] = record["surfaces"][0]["candidates"]
        assert c3["contradiction"] == {"kind": "closure_unknown", "observed_descendants": [], "count": 0}
        assert any("[3617]" in r.getMessage() for r in caplog.records)

    def test_the_closure_gateway_is_the_cascades_own_discovery(self, graph: Graph, settings: Any) -> None:
        """What derivation calls 'under it' is what a contained cascade would retire: through the
        declared containment edges only, root excluded, None past the configured cap — and the
        cap is the configured one, not a caller's."""
        import inspect

        from tap_grid.services import contained_closure

        g = self._grandchild(graph.c[2])
        assert contained_closure(graph.p.pk) == frozenset({graph.c[0].pk, graph.c[1].pk, graph.c[2].pk, g.pk})
        assert contained_closure(graph.c[2].pk) == frozenset({g.pk})
        assert contained_closure(graph.c[0].pk) == frozenset()
        assert contained_closure(graph.r.pk) == frozenset(), "a reference is not containment"
        assert contained_closure(uuid.uuid4()) == frozenset()
        assert "cap" not in inspect.signature(contained_closure).parameters, "no caller widens the cap"
        settings.TAP_CASCADE_MAX_CLOSURE = 2
        assert contained_closure(graph.p.pk) is None

    def test_a_withdrawn_child_is_checked_the_same_way(self, graph: Graph) -> None:
        """Withdrawal takes no evidence from this run except the contradiction check."""
        g = self._grandchild(graph.c[2])
        previous_write = graph.observe(graph.p, *graph.c)
        previous = _run(_surface(graph.p, applied_batches=[str(previous_write.entity_id)]))
        write = graph.observe(graph.q, g)  # this run: scope moved to Q; g still seen
        run = _run(_surface(graph.q, applied_batches=[str(write.entity_id)]))
        record = derive_candidates(
            run,
            produced_batches=[str(write.entity_id)],
            previous_batch=previous,
            previous_produced_batches=[str(previous_write.entity_id)],
        )
        withdrawn = next(s for s in record["surfaces"] if s["outcome"] == "withdrawn")
        by_id = {c["entity_id"]: c for c in withdrawn["candidates"]}
        assert by_id[str(graph.c[2].pk)]["contradiction"]["observed_descendants"] == [str(g.pk)]
        assert by_id[str(graph.c[0].pk)]["contradiction"] is None
