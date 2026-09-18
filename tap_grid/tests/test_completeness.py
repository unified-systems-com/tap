"""The completeness statement (``req-grid-reconcile-evidence``, phase 4 slice 1, Issue# 574 - tap).

Six attributes per listing surface, recorded on the run's Batch under
``metadata["completeness"]``; ``applied`` and ``reconcilable`` derived by the recorder;
consistency never inferred, a count mismatch refuses, a filtered surface needs a passing
control. Nothing here is a verdict.

The batch lifecycle helpers (`create_batch` / `close_batch` / `fail_batch`) are the
intentional below-service-layer setup: the statement is bookkeeping ON a batch, and the
batch lifecycle module is its home.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.utils import timezone

from tap_grid.batch import batch_summary, close_batch, create_batch, fail_batch
from tap_grid.completeness import CompletenessError, completeness_of, record_completeness
from tap_grid.models import Batch, BatchStatus


def _closed() -> Batch:
    return close_batch(create_batch(source="test.completeness"))


def _failed() -> Batch:
    return fail_batch(create_batch(source="test.completeness"), "boom")


def _surface(**overrides: Any) -> dict[str, Any]:
    now = timezone.now().isoformat()
    base: dict[str, Any] = {
        "relation": "repository.workflows",
        "filter": None,
        "subject": "repo:unified-systems-com/tap",
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
        "reasons": {"source_consistent": "github: no snapshot promise across pages"},
    }
    base.update(overrides)
    return base


def _record(*surfaces: dict[str, Any]) -> tuple[Batch, dict[str, Any]]:
    run = create_batch(source="test.completeness.run")
    statement = record_completeness(run, list(surfaces))
    run.refresh_from_db()
    return run, statement


@pytest.mark.django_db
class TestSixAttributesPerSurface:
    @pytest.mark.spec("req-grid-reconcile-evidence-1")
    def test_every_attribute_is_recorded_separately(self) -> None:
        good = _closed()
        run, statement = _record(_surface(applied_batches=[str(good.entity_id)]))
        [s] = statement["surfaces"]
        for attribute in (
            "scope_authorized",
            "enumeration_complete",
            "source_consistent",
            "interval",
            "admitted",
            "applied",
        ):
            assert attribute in s, attribute
        assert s["applied"] is True and s["reconcilable"] is True
        assert completeness_of(run) == statement

    @pytest.mark.spec("req-grid-reconcile-evidence-1")
    def test_a_negative_or_unknown_attribute_without_a_reason_is_refused(self) -> None:
        run = create_batch(source="test")
        with pytest.raises(CompletenessError) as excinfo:
            record_completeness(run, [_surface(scope_authorized=False)])
        assert excinfo.value.code == "reason_required"
        run.refresh_from_db()
        assert completeness_of(run) is None, "a refused statement writes nothing"

    @pytest.mark.spec("req-grid-reconcile-evidence-1")
    def test_a_negative_attribute_with_a_reason_is_recorded_as_negative(self) -> None:
        run, statement = _record(
            _surface(
                scope_authorized=None,
                reasons={"scope_authorized": "credential scope not observable", "source_consistent": "n/a"},
            )
        )
        [s] = statement["surfaces"]
        assert s["scope_authorized"] is None and s["reconcilable"] is False
        assert s["reasons"]["scope_authorized"].startswith("credential scope")

    def test_nothing_recorded_is_none_not_complete(self) -> None:
        run = create_batch(source="test")
        assert completeness_of(run) is None
        summary = batch_summary(run.entity_id, with_counts=False)
        assert summary is not None and summary["completeness"] is None

    def test_only_an_open_batch_takes_a_statement(self) -> None:
        with pytest.raises(CompletenessError) as excinfo:
            record_completeness(_closed(), [_surface()])
        assert excinfo.value.code == "batch_not_open"


@pytest.mark.django_db
class TestConsistencyIsNeverInferred:
    @pytest.mark.spec("req-grid-reconcile-evidence-2")
    def test_true_without_a_named_promise_is_refused(self) -> None:
        run = create_batch(source="test")
        with pytest.raises(CompletenessError) as excinfo:
            record_completeness(run, [_surface(source_consistent=True, reasons={})])
        assert excinfo.value.code == "consistency_unpromised"

    @pytest.mark.spec("req-grid-reconcile-evidence-2")
    def test_true_with_the_sources_promise_is_recorded(self) -> None:
        _, statement = _record(
            _surface(source_consistent=True, source_promise="kubernetes: list resourceVersion snapshot", reasons={})
        )
        assert statement["surfaces"][0]["source_consistent"] is True

    @pytest.mark.spec("req-grid-reconcile-evidence-2")
    def test_complete_enumeration_and_matching_counts_do_not_promote_unknown(self) -> None:
        good = _closed()
        _, statement = _record(_surface(count_observed=7, count_reported=7, applied_batches=[str(good.entity_id)]))
        [s] = statement["surfaces"]
        assert s["enumeration_complete"] is True and s["reconcilable"] is True
        assert (
            s["source_consistent"] == "unknown"
        ), "finishing pagination and a matching count prove nothing about a snapshot"


@pytest.mark.django_db
class TestCountMismatchRefuses:
    @pytest.mark.spec("req-grid-reconcile-evidence-3")
    def test_a_mismatch_is_recorded_and_makes_the_surface_not_reconcilable(self) -> None:
        good = _closed()
        _, statement = _record(_surface(count_observed=41, count_reported=42, applied_batches=[str(good.entity_id)]))
        [s] = statement["surfaces"]
        assert s["enumeration_complete"] is True, "the walk itself finished"
        assert s["reconcilable"] is False
        assert s["reasons"]["count"] == "count_mismatch: observed 41, reported 42"

    @pytest.mark.spec("req-grid-reconcile-evidence-3")
    def test_a_missing_reported_total_is_not_a_mismatch(self) -> None:
        good = _closed()
        _, statement = _record(_surface(count_observed=41, count_reported=None, applied_batches=[str(good.entity_id)]))
        assert statement["surfaces"][0]["reconcilable"] is True


@pytest.mark.django_db
class TestFilterPositiveControl:
    @pytest.mark.spec("req-grid-reconcile-evidence-4")
    def test_a_failed_control_marks_enumeration_not_complete(self) -> None:
        _, statement = _record(_surface(filter="state=open", filter_control={"value_changed": False}))
        [s] = statement["surfaces"]
        assert s["enumeration_complete"] is False and s["reconcilable"] is False
        assert s["reasons"]["enumeration_complete"].startswith("filter_ignored")

    @pytest.mark.spec("req-grid-reconcile-evidence-4")
    def test_a_filter_with_no_control_is_not_complete_either(self) -> None:
        _, statement = _record(_surface(filter="state=open"))
        [s] = statement["surfaces"]
        assert s["enumeration_complete"] is False
        assert s["reasons"]["enumeration_complete"].startswith("filter_uncontrolled")

    @pytest.mark.spec("req-grid-reconcile-evidence-4")
    def test_a_passing_control_leaves_the_walks_verdict_alone(self) -> None:
        good = _closed()
        _, statement = _record(
            _surface(filter="state=open", filter_control={"value_changed": True}, applied_batches=[str(good.entity_id)])
        )
        assert statement["surfaces"][0]["enumeration_complete"] is True


@pytest.mark.django_db
class TestStatementShape:
    @pytest.mark.spec("req-grid-reconcile-evidence-5")
    def test_the_record_names_relation_filter_subject_and_interval(self) -> None:
        _, statement = _record(_surface(filter="state=open", filter_control={"value_changed": True}))
        [s] = statement["surfaces"]
        assert s["relation"] == "repository.workflows"
        assert s["filter"] == "state=open"
        assert s["subject"] == "repo:unified-systems-com/tap"
        assert set(s["interval"]) == {"first", "last"}
        assert statement["recorded_at"]

    @pytest.mark.spec("req-grid-reconcile-evidence-5")
    def test_a_surface_without_a_subject_does_not_fit_the_schema(self) -> None:
        run = create_batch(source="test")
        surface = _surface()
        del surface["subject"]
        with pytest.raises(CompletenessError) as excinfo:
            record_completeness(run, [surface])
        assert excinfo.value.code == "invalid_statement"
        assert "subject" in str(excinfo.value)

    def test_an_undescribed_extra_field_does_not_fit_the_schema(self) -> None:
        run = create_batch(source="test")
        with pytest.raises(CompletenessError) as excinfo:
            record_completeness(run, [_surface(complete=True)])
        assert excinfo.value.code == "invalid_statement"


@pytest.mark.django_db
class TestAppliedIsDerived:
    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_a_failed_write_batch_is_not_applied_and_not_reconcilable(self) -> None:
        bad = _failed()
        _, statement = _record(_surface(admitted=True, applied_batches=[str(bad.entity_id)]))
        [s] = statement["surfaces"]
        assert s["admitted"] is True and s["applied"] is False and s["reconcilable"] is False
        assert s["reasons"]["applied"].startswith("batch_not_committed")

    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_admitted_with_no_batch_is_not_applied(self) -> None:
        _, statement = _record(_surface(applied_batches=[]))
        [s] = statement["surfaces"]
        assert s["applied"] is False and s["reasons"]["applied"].startswith("no_batch")

    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_an_open_or_unknown_batch_is_not_applied(self) -> None:
        still_open = create_batch(source="test")
        _, statement = _record(
            _surface(applied_batches=[str(still_open.entity_id)]),
            _surface(applied_batches=[str(uuid.uuid4())]),
        )
        a, b = statement["surfaces"]
        assert a["applied"] is False and a["reasons"]["applied"].startswith("batch_not_committed")
        assert b["applied"] is False and b["reasons"]["applied"].startswith("batch_missing")

    @pytest.mark.spec("req-grid-reconcile-evidence-6")
    def test_authoring_applied_or_reconcilable_is_refused(self) -> None:
        run = create_batch(source="test")
        for field in ("applied", "reconcilable"):
            with pytest.raises(CompletenessError) as excinfo:
                record_completeness(run, [_surface(**{field: True})])
            assert excinfo.value.code == "derived_not_authored"


@pytest.mark.django_db
class TestUnchangedObservationsCount:
    @pytest.mark.spec("req-grid-reconcile-evidence-7")
    def test_a_no_op_reimport_still_applies(self) -> None:
        """Two imports of the same node under fresh batch ids: the second changes no field,
        but its batch committed, so the surface is applied. `applied` is read from the
        batch's status, never from Entity.version — which is why this test does not look
        at the version at all (the importer's replace currently bumps it even for an
        unchanged payload; that is tap#322's territory, not this requirement's)."""
        from tap_grid.grift import grift_import
        from tap_grid.models import Entity
        from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _character_node, _minimal_doc

        nid = str(uuid.uuid4())
        first = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[_character_node(nid)])]))
        assert first.success
        name_before = Entity.objects.get(pk=uuid.UUID(nid)).name
        second_bid = _batch_entity_id()
        second = grift_import(_minimal_doc([_batch_container(second_bid, nodes=[_character_node(nid)])]))
        assert second.success and second.counts.nodes_imported == 1
        assert Entity.objects.get(pk=uuid.UUID(nid)).name == name_before, "nothing observable changed"
        assert Batch.objects.get(entity_id=second_bid).status == BatchStatus.CLOSED
        _, statement = _record(_surface(applied_batches=[second_bid]))
        assert statement["surfaces"][0]["applied"] is True


@pytest.mark.django_db
def test_batch_summary_carries_the_statement() -> None:
    good = _closed()
    run, statement = _record(_surface(applied_batches=[str(good.entity_id)]))
    summary = batch_summary(run.entity_id, with_counts=False)
    assert summary is not None and summary["completeness"] == statement
