"""The checker checked (Issue# 588 - tap): deliberately corrupted observations must be
rejected, each with a message naming what is wrong. A checker that only ever sees correct
runs is a presence test wearing a correctness test's clothes."""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import F

from tap_grid.batch import record_batch_event
from tap_grid.cascade_corpus.loader import Scenario, load_corpus
from tap_grid.cascade_corpus.runner import (
    Built,
    apply_blocks,
    apply_containment,
    build,
    check,
    event_counts,
    event_delta,
    snapshot,
)
from tap_grid.models import Batch, BatchEvent, BatchEventType, Entity
from tap_grid.services import delete_node


def _scenario(name_fragment: str) -> Scenario:
    [s] = [s for s in load_corpus() if name_fragment in s.name]
    return s


@pytest.fixture
def observed(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A real, correct run of `metadata is inherited by every cascaded node` (R→A→B), with the
    before/after observations kept apart so a test can tamper between the run and the check."""
    scenario = _scenario("metadata is inherited by every cascaded node")
    apply_containment(scenario, monkeypatch)
    built = build(scenario)
    apply_blocks(scenario, monkeypatch)
    before, events_before = snapshot(), event_counts()
    batches_before = dict(Batch.objects.values_list("entity_id", "status"))
    result = delete_node(
        built.node_ids[scenario.target], reason=scenario.reason, metadata=scenario.metadata, cascade="contained"
    )
    assert result.success
    return {
        "scenario": scenario,
        "built": built,
        "result": result,
        "before": before,
        "events_before": events_before,
        "batches_before": batches_before,
    }


def _check(obs: dict[str, Any]) -> list[str]:
    return check(
        obs["scenario"],
        obs["built"],
        obs["result"],
        obs["before"],
        snapshot(),
        event_delta(obs["events_before"], event_counts()),
        obs["batches_before"],
    )


def _event(built: Built, ref: str, event_type: str) -> BatchEvent:
    eid = built.node_ids.get(ref) or built.edge_ids[ref]
    event = BatchEvent.objects.filter(entity_id=eid, event_type=event_type).order_by("-timestamp", "-pk").first()
    assert event is not None
    return event


@pytest.mark.cascade_corpus
@pytest.mark.django_db
@pytest.mark.spec("req-grid-cascade-corpus-runner-2")
class TestTheCheckerRejects:
    def test_a_correct_run_passes(self, observed: dict[str, Any]) -> None:
        assert _check(observed) == []

    def test_collateral_retirement(self, observed: dict[str, Any]) -> None:
        """An entity outside the expected set that lost its liveness is reported by ref or id."""
        from tap_grid.services import create_node

        outsider = create_node("grid_fixtures__node", {"name": "outsider"})
        assert outsider.success and outsider.entity_id is not None
        observed["before"] = snapshot()  # the outsider is part of "before", live
        Entity.objects.filter(pk=outsider.entity_id).update(
            deleted_at=Entity.objects.get(pk=outsider.entity_id).created_at
        )
        failures = _check(observed)
        assert any("must be untouched" in f for f in failures), failures

    def test_a_double_version_bump_on_a_retired_node(self, observed: dict[str, Any]) -> None:
        Entity.objects.filter(pk=observed["built"].node_ids["A"]).update(version=F("version") + 1)
        failures = _check(observed)
        assert any("A version" in f and "exactly once" in f for f in failures), failures

    def test_a_duplicate_delete_event(self, observed: dict[str, Any]) -> None:
        record_batch_event(
            entity=Entity.objects.get(pk=observed["built"].node_ids["B"]),
            event_type="delete",
            model_name="",
            actor=None,
            batch_id=observed["result"].batch_id,
            metadata={"reason": "cascaded"},
        )
        failures = _check(observed)
        assert any("events recorded" in f and "B:delete" in f for f in failures), failures

    def test_a_missing_edge_event(self, observed: dict[str, Any]) -> None:
        _event(observed["built"], "e_A_B", BatchEventType.UNLINK).delete()
        failures = _check(observed)
        assert any("events recorded" in f and "e_A_B:unlink" in f for f in failures), failures

    def test_a_wrong_root_reason_on_a_descendant(self, observed: dict[str, Any]) -> None:
        event = _event(observed["built"], "B", BatchEventType.DELETE)
        event.metadata = {**event.metadata, "root_reason": "operator"}
        event.save(update_fields=["metadata"])
        failures = _check(observed)
        assert any("B: root_reason 'operator'" in f for f in failures), failures

    def test_a_missing_cascade_root_on_an_edge(self, observed: dict[str, Any]) -> None:
        event = _event(observed["built"], "e_R_A", BatchEventType.UNLINK)
        event.metadata = {k: v for k, v in event.metadata.items() if k != "cascade_root"}
        event.save(update_fields=["metadata"])
        failures = _check(observed)
        assert any("e_R_A: edge cascade_root None" in f for f in failures), failures

    def test_a_wrong_discoverer(self, observed: dict[str, Any]) -> None:
        event = _event(observed["built"], "B", BatchEventType.DELETE)
        event.metadata = {**event.metadata, "consequence_of": str(observed["built"].node_ids["R"])}
        event.save(update_fields=["metadata"])
        failures = _check(observed)
        assert any("B: consequence_of 'R'" in f for f in failures), failures

    def test_dropped_inherited_metadata_on_the_root(self, observed: dict[str, Any]) -> None:
        event = _event(observed["built"], "R", BatchEventType.DELETE)
        event.metadata = {k: v for k, v in event.metadata.items() if k != "scope"}
        event.save(update_fields=["metadata"])
        failures = _check(observed)
        assert any("R: inherited metadata scope=None" in f for f in failures), failures
