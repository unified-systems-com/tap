"""Edge authority, applied: the reconcile verb removes what a complete claim proposed, behind the
fence, and holds a claim that would empty its scope.

Spec: ``req-grid-reconcile-edge-authority`` (``-11`` to ``-13``) in
``tap_grid/specs/spec-grid-reconcile.md`` (Issue# 920 - tap). Every proposal here is a real one, written
by the importer's dry-run under a stamped run (``test_grift_edge_authority``); the stage is then
called as ``reconcile_run`` calls it, with authority on. Arming itself, and the stage reached through
a real collection run, are ``tap_cares/tests/test_edge_authority_run.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tap_grid.grift import grift_import
from tap_grid.models import BatchEvent, BatchEventType, Entity
from tap_grid.reconcile import (
    APPLIED,
    EDGE_AUTHORITY_KEY,
    GONE,
    HELD,
    REFUSED,
    REJECTED_STALE,
    WHOLE_SCOPE_HOLD_FLOOR,
    _apply_edge_authority,
)
from tap_grid.service_types import WriteOperation
from tap_grid.services import write_batch
from tap_grid.tests.test_grift_edge_authority import _claim, _edge, _import, _link, _run, _seed, star  # noqa: F401
from tap_grid.tests.test_grift_edge_endpoints import _doc

SPEC = {n: pytest.mark.spec(f"req-grid-reconcile-edge-authority-{n}") for n in (11, 12, 13)}

pytestmark = pytest.mark.django_db


def _apply(run: Any, *results: Any) -> dict[str, Any]:
    """The stage, over the run's own batches: the claiming imports and the run's lifecycle batch."""
    produced = {str(r.imported_batches[0].batch_entity_id) for r in results} | {str(run.entity_id)}
    return _apply_edge_authority(run, produced_batches=produced)


def _by_edge(record: dict[str, Any]) -> dict[str, list[str]]:
    outcomes: dict[str, list[str]] = {}
    for entry in record["entries"]:
        outcomes.setdefault(entry["edge_id"], []).append(entry["outcome"])
    return outcomes


def _live(edge_id: str) -> bool:
    return Entity.objects.filter(pk=uuid.UUID(edge_id), deleted_at__isnull=True).exists()


class TestApplying:
    @SPEC[12]
    def test_a_proposal_is_removed_as_an_authority_unlink(self, star: dict[str, str]) -> None:
        with _run() as run:
            claimed = _import(
                _claim({"entity_id": star["hub"]}), edges=[_edge(star["hub"], star["b"], edge_id=star["hub_b"])]
            )
        assert claimed.success, claimed.errors
        record = _apply(run, claimed)
        assert _by_edge(record) == {star["hub_c"]: [APPLIED]}
        assert record["counts"][APPLIED] == 1 and record["held_claims"] == []
        assert not _live(star["hub_c"]) and _live(star["hub_b"]), "only the proposed edge is removed"
        unlink = BatchEvent.objects.get(entity_id=uuid.UUID(star["hub_c"]), event_type=BatchEventType.UNLINK)
        assert unlink.metadata["reason"] == "authority", "the closed vocabulary's word, not whatever the constant holds"
        audit = unlink.metadata[EDGE_AUTHORITY_KEY]
        assert audit["proposal_event_id"] == record["entries"][0]["proposal_event_id"]
        assert audit["run"] == str(run.entity_id)
        assert audit["claim"]["anchor_entity_id"] == star["hub"] and audit["released_by"] is None

    @SPEC[12]
    def test_an_edge_proposed_by_two_claims_is_removed_once(self, star: dict[str, str]) -> None:
        keep = _edge(star["hub"], star["b"], edge_id=star["hub_b"])
        with _run() as run:
            first = _import(_claim({"entity_id": star["hub"]}), edges=[keep])
            second = _import(_claim({"entity_id": star["hub"]}), edges=[keep])
        record = _apply(run, first, second)
        assert sorted(_by_edge(record)[star["hub_c"]]) == sorted([APPLIED, GONE])
        assert BatchEvent.objects.filter(entity_id=uuid.UUID(star["hub_c"]), event_type=BatchEventType.UNLINK).count() == 1

    @SPEC[12]
    def test_an_edge_already_gone_is_recorded_gone(self, star: dict[str, str]) -> None:
        with _run() as run:
            claimed = _import(
                _claim({"entity_id": star["hub"]}), edges=[_edge(star["hub"], star["b"], edge_id=star["hub_b"])]
            )
        removed = write_batch(
            [WriteOperation(verb="delete_edge", target=star["hub_c"], reason="operator")],
            batch_name="remove hub -> c by hand",
            batch_description="an operator removes the edge before the reconcile applies",
        )
        assert removed.success, removed.errors
        record = _apply(run, claimed)
        assert _by_edge(record) == {star["hub_c"]: [GONE]}

    @SPEC[12]
    def test_an_internal_only_type_is_refused_at_apply(
        self, star: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preflight already refuses claiming one; the apply path refuses it again, should one reach it."""
        with _run() as run:
            claimed = _import(
                _claim({"entity_id": star["hub"]}), edges=[_edge(star["hub"], star["b"], edge_id=star["hub_b"])]
            )
        monkeypatch.setattr("tap_grid.constraints.is_internal_edge_type", lambda edge_type: True)
        record = _apply(run, claimed)
        assert _by_edge(record) == {star["hub_c"]: [REFUSED]}
        assert _live(star["hub_c"])


class TestTheFenceAtApply:
    @SPEC[11]
    def test_an_edge_observed_after_the_proposal_is_rejected_stale(self, star: dict[str, str]) -> None:
        with _run() as run:
            claimed = _import(
                _claim({"entity_id": star["hub"]}), edges=[_edge(star["hub"], star["b"], edge_id=star["hub_b"])]
            )
            # Another batch of this run sends hub -> c after the claim: the claim's read is out of date.
            again = grift_import(_doc(edges=[_edge(star["hub"], star["c"], edge_id=star["hub_c"])]))
            assert again.success, again.errors
        record = _apply(run, claimed)
        assert _by_edge(record) == {star["hub_c"]: [REJECTED_STALE]}
        assert _live(star["hub_c"])
        (entry,) = record["entries"]
        assert str(again.imported_batches[0].batch_entity_id) in entry["error"]


class TestTheWholeScopeHold:
    @SPEC[13]
    def test_a_claim_that_asserts_none_of_its_scope_is_held(self) -> None:
        ids = _seed("anchor", *(f"t{i}" for i in range(WHOLE_SCOPE_HOLD_FLOOR)))
        edges = _link(*(_edge(ids["anchor"], ids[f"t{i}"]) for i in range(WHOLE_SCOPE_HOLD_FLOOR)))
        with _run() as run:
            claimed = _import(_claim({"entity_id": ids["anchor"]}))
        record = _apply(run, claimed)
        assert _by_edge(record) == {e: [HELD] for e in edges}
        assert all(_live(e) for e in edges), "a held claim removes nothing"
        (held,) = record["held_claims"]
        assert (held["anchor_entity_id"], held["in_scope"], held["released"]) == (
            ids["anchor"],
            WHOLE_SCOPE_HOLD_FLOOR,
            None,
        )
        assert held["claim_event_id"] == record["entries"][0]["claim_event_id"]

    @SPEC[13]
    def test_a_scope_below_the_floor_is_applied(self) -> None:
        ids = _seed("anchor", "t0", "t1")
        edges = _link(_edge(ids["anchor"], ids["t0"]), _edge(ids["anchor"], ids["t1"]))
        with _run() as run:
            claimed = _import(_claim({"entity_id": ids["anchor"]}))
        record = _apply(run, claimed)
        assert _by_edge(record) == {e: [APPLIED] for e in edges} and record["held_claims"] == []

    @SPEC[13]
    def test_a_held_claim_does_not_hold_the_others(self, star: dict[str, str]) -> None:
        ids = _seed("anchor", *(f"t{i}" for i in range(WHOLE_SCOPE_HOLD_FLOOR)))
        held_edges = _link(*(_edge(ids["anchor"], ids[f"t{i}"]) for i in range(WHOLE_SCOPE_HOLD_FLOOR)))
        with _run() as run:
            whole = _import(_claim({"entity_id": ids["anchor"]}))
            partial = _import(
                _claim({"entity_id": star["hub"]}), edges=[_edge(star["hub"], star["b"], edge_id=star["hub_b"])]
            )
        record = _apply(run, whole, partial)
        outcomes = _by_edge(record)
        assert {outcomes[e][0] for e in held_edges} == {HELD}
        assert outcomes[star["hub_c"]] == [APPLIED]
        assert not _live(star["hub_c"]) and all(_live(e) for e in held_edges)


class TestTheRecord:
    @SPEC[12]
    def test_a_record_that_drifted_from_the_schema_is_refused(self) -> None:
        """The reconcile verb's writer validates the whole record, edge authority included, before storing."""
        from tap_grid.candidates import record_candidates
        from tap_grid.falsifiers import falsify_candidates, verdicts_of
        from tap_grid.reconcile import ReconcileError, _store
        from tap_grid.write_guard import unguarded_write
        from tap_web.tests.test_batch_viewer_candidates import _run_with_statement

        run = _run_with_statement()
        record_candidates(run, produced_batches=[])
        run.refresh_from_db()
        falsify_candidates(run)
        record = verdicts_of(run)
        assert record is not None
        record[EDGE_AUTHORITY_KEY] = {"authority": "on", "counts": None, "held_claims": [], "entries": [], "extra": 1}
        with unguarded_write(), pytest.raises(ReconcileError, match="edge_authority"):
            _store(run, record)
        run.refresh_from_db()
        assert EDGE_AUTHORITY_KEY not in (verdicts_of(run) or {}), "nothing was stored"
