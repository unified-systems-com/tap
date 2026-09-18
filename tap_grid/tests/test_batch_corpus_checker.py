"""The checker checked (Issue# 603 - tap, in the cascade corpus's tradition — Issue# 588 - tap):
deliberately corrupted observations must be rejected, each with a message naming what is
wrong. A checker that only ever sees correct runs is a presence test wearing a correctness
test's clothes."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest
from django.db.models import F

from tap_grid.batch import record_batch_event
from tap_grid.batch_corpus.loader import Scenario, load_corpus
from tap_grid.batch_corpus.runner import Built, build, check
from tap_grid.cascade_corpus.runner import event_counts, event_delta, snapshot
from tap_grid.models import Batch, BatchEvent, Entity
from tap_grid.services import create_node

pytestmark = [pytest.mark.batch_corpus, pytest.mark.django_db, pytest.mark.spec("req-grid-batch-corpus-runner-2")]


def _scenario(name_fragment: str) -> Scenario:
    [s] = [s for s in load_corpus() if name_fragment in s.name]
    return s


@pytest.fixture
def observed() -> dict[str, Any]:
    """A real, correct run of `an id node links to a ref node that found an existing row`
    (grid panel A; import creates X and an edge X→A, ref p finds A), with the observations
    kept apart so a test can tamper between the run and the check."""
    from tap_grid.batch_corpus import runner

    scenario = _scenario("an id node links to a ref node that found an existing row")
    built = build(scenario)
    events_before = event_counts()
    results = [runner._import(scenario, imp, built) for imp in scenario.imports]
    return {"scenario": scenario, "built": built, "results": results, "events_before": events_before}


def _check(obs: dict[str, Any]) -> list[str]:
    return check(
        obs["scenario"], obs["built"], obs["results"], snapshot(), event_delta(obs["events_before"], event_counts())
    )


def _id(obs: dict[str, Any], name: str) -> uuid.UUID:
    built: Built = obs["built"]
    return built.ids[name]


class TestTheCheckerRejects:
    def test_a_correct_run_passes(self, observed: dict[str, Any]) -> None:
        assert _check(observed) == []

    def test_collateral_tombstone_on_an_outsider(self, observed: dict[str, Any]) -> None:
        """An entity outside the scenario that lost its liveness is reported by id."""
        outsider = create_node("grid_fixtures__node", {"name": "outsider"})
        assert outsider.success and outsider.entity_id is not None
        observed["built"].initial[uuid.UUID(str(outsider.entity_id))] = (False, 1)
        Entity.objects.filter(pk=outsider.entity_id).update(
            deleted_at=Entity.objects.get(pk=outsider.entity_id).created_at
        )
        failures = _check(observed)
        assert any("must be untouched" in f for f in failures), failures

    def test_a_double_version_bump_on_the_replaced_row(self, observed: dict[str, Any]) -> None:
        Entity.objects.filter(pk=_id(observed, "A")).update(version=F("version") + 1)
        failures = _check(observed)
        assert any(f.startswith("A version 3, expected 2") for f in failures), failures

    def test_a_row_that_should_exist_and_does_not(self, observed: dict[str, Any]) -> None:
        Entity.objects.filter(pk=_id(observed, "X")).delete()
        failures = _check(observed)
        assert any("X should exist and has no row" in f for f in failures), failures

    def test_a_duplicate_create_event(self, observed: dict[str, Any]) -> None:
        record_batch_event(
            entity=Entity.objects.get(pk=_id(observed, "X")),
            event_type="create",
            model_name="",
            actor=None,
            batch_id=str(_id(observed, "b1")),
            metadata={},
        )
        failures = _check(observed)
        assert any("events recorded" in f and "X:createx2" in f for f in failures), failures

    def test_a_missing_link_event(self, observed: dict[str, Any]) -> None:
        BatchEvent.objects.filter(entity_id=_id(observed, "e"), event_type="link").delete()
        failures = _check(observed)
        assert any("events recorded" in f and "expected" in f and "e:linkx1" in f for f in failures), failures

    def test_a_wrong_spine_name(self, observed: dict[str, Any]) -> None:
        Entity.objects.filter(pk=_id(observed, "A")).update(name="not what the envelope said")
        failures = _check(observed)
        assert any("A spine name 'not what the envelope said'" in f for f in failures), failures

    def test_an_unexpected_new_entity(self, observed: dict[str, Any]) -> None:
        stray = create_node("grid_fixtures__node", {"name": "stray"})
        assert stray.success
        failures = _check(observed)
        assert any("unexpected new entities" in f for f in failures), failures

    def test_a_missing_batch_row(self, observed: dict[str, Any]) -> None:
        Batch.all_objects.filter(entity_id=_id(observed, "b1")).delete()
        failures = _check(observed)
        assert any("batch b1 should be committed" in f for f in failures), failures

    def test_a_doctored_result_success(self, observed: dict[str, Any]) -> None:
        observed["results"] = [
            dataclasses.replace(observed["results"][0], success=False, errors=[("execution_failed", "$")])
        ]
        failures = _check(observed)
        assert any(f.startswith("import 0: success False, expected True") for f in failures), failures
        assert any("import 0: errors [('execution_failed', '$')], expected []" in f for f in failures), failures

    def test_a_ref_reported_as_resolving_elsewhere(self, observed: dict[str, Any]) -> None:
        r = observed["results"][0]
        (bid,) = r.resolved
        observed["results"] = [dataclasses.replace(r, resolved={bid: {"p": str(_id(observed, "X"))}})]
        failures = _check(observed)
        assert any("ref p should have resolved to A, reported X" in f for f in failures), failures

    def test_a_purged_row_that_survived(self) -> None:
        """The purge family's own shape: a row the model says is gone, still observed."""
        from django.test import override_settings

        from tap_grid.batch_corpus import runner

        scenario = _scenario("a purge of an edge leaves both endpoints untouched")
        built = build(scenario)
        events_before = event_counts()
        with override_settings(DEBUG=True):
            results = [runner._import(scenario, imp, built) for imp in scenario.imports]
        # A corrupted observation: the purge reported applied, the edge's row is still in the snapshot.
        after = snapshot() | {built.ids["e"]: (False, 1)}
        failures = check(scenario, built, results, after, event_delta(events_before, event_counts()))
        assert any("e should have no row and has one" in f for f in failures), failures
