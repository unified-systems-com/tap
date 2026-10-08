"""Tests for the CollectionJob model and HAS_COLLECTION_JOB edge.

Covers:
  req-tap-cares-collector-job-model
  req-tap-cares-collector-job-edge
  req-tap-cares-collector-job-lifecycle
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError

from tap_cares.models import CollectionJob, CollectionJobStatus, Collector


def _job_kwargs(**overrides):
    base = {
        "name": "Test Job",
        "description": "fixture",
    }
    base.update(overrides)
    return base


def _make_collector(suffix: str = ""):
    return Collector.objects.create(
        name=f"Test Collector {suffix}".strip(),
        description="",
        collector_registry=f"tap_cares.tests.fakes:dummy-{suffix or 'x'}",
    )


# ---------------------------------------------------------------------------
# Entity spine + class constants
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollectionJobIsEntity:
    def test_entity_type_constant(self):
        assert CollectionJob.ENTITY_TYPE == "collection_job"

    def test_default_dimensions(self):
        assert CollectionJob.DEFAULT_DIMENSIONS == {"tap_cares": "collection_job"}

    def test_creates_backing_entity_on_save(self):
        j = CollectionJob.objects.create(**_job_kwargs())
        assert j.entity_id is not None
        assert j.entity.entity_type == "collection_job"

    def test_save_applies_default_dimension(self):
        j = CollectionJob.objects.create(**_job_kwargs())
        assert j.entity.dimensions == {"tap_cares": "collection_job"}


# ---------------------------------------------------------------------------
# Lifecycle status enum — req-tap-cares-collector-job-lifecycle-{1,6,7}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStatusEnum:
    def test_default_status_is_ready(self):
        j = CollectionJob.objects.create(**_job_kwargs())
        assert j.status == "READY"

    def test_status_values_are_uppercase(self):
        values = {choice.value for choice in CollectionJobStatus}
        assert values == {"READY", "RUNNING", "FAILED", "SUCCESSFUL"}

    def test_status_display_labels_are_title_case(self):
        labels = {choice.value: choice.label for choice in CollectionJobStatus}
        assert labels == {
            "READY": "Ready",
            "RUNNING": "Running",
            "FAILED": "Failed",
            "SUCCESSFUL": "Successful",
        }

    @pytest.mark.parametrize("value", ["READY", "RUNNING", "FAILED", "SUCCESSFUL"])
    def test_valid_status_accepted(self, value):
        j = CollectionJob(**_job_kwargs(status=value))
        j.full_validate()  # does not raise

    def test_invalid_status_rejected(self):
        j = CollectionJob(**_job_kwargs(status="ready"))  # lowercase = invalid
        with pytest.raises(ValidationError) as exc_info:
            j.full_validate()
        assert "status" in exc_info.value.message_dict


# ---------------------------------------------------------------------------
# Status display projection — req-tap-cares-collector-job-model-8
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStatusDisplay:
    @pytest.mark.parametrize(
        "stored,expected",
        [
            ("READY", "Ready"),
            ("RUNNING", "Running"),
            ("FAILED", "Failed"),
            ("SUCCESSFUL", "Successful"),
        ],
    )
    def test_get_status_display_returns_title_label(self, stored, expected):
        j = CollectionJob.objects.create(**_job_kwargs(status=stored))
        assert j.get_status_display() == expected

    def test_status_display_property_matches_django_helper(self):
        j = CollectionJob.objects.create(**_job_kwargs(status="RUNNING"))
        assert j.status_display == j.get_status_display() == "Running"


# ---------------------------------------------------------------------------
# task_result_id — req-tap-cares-collector-job-model-6
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTaskResultId:
    def test_default_is_empty_string(self):
        j = CollectionJob.objects.create(**_job_kwargs())
        assert j.task_result_id == ""

    def test_accepts_32_char_random_string_default_backends(self):
        # Mirrors get_random_string(32) from django.tasks immediate/dummy backends.
        rid = "a" * 32
        j = CollectionJob.objects.create(**_job_kwargs(task_result_id=rid))
        assert j.task_result_id == rid

    def test_accepts_longer_ids_under_cap(self):
        rid = "x" * 128
        j = CollectionJob(**_job_kwargs(task_result_id=rid))
        j.full_validate()
        j.save()
        assert CollectionJob.objects.get(pk=j.pk).task_result_id == rid

    def test_over_cap_rejected_by_schema(self):
        j = CollectionJob(**_job_kwargs(task_result_id="x" * 129))
        with pytest.raises(ValidationError) as exc_info:
            j.full_validate()
        assert "task_result_id" in exc_info.value.message_dict


# ---------------------------------------------------------------------------
# summary — req-tap-cares-collector-job-model-7
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummary:
    def test_default_is_empty_string(self):
        j = CollectionJob.objects.create(**_job_kwargs())
        assert j.summary == ""

    def test_under_cap_accepted(self):
        j = CollectionJob(**_job_kwargs(summary="imported 7 indicators"))
        j.full_validate()

    def test_over_cap_rejected(self):
        j = CollectionJob(**_job_kwargs(summary="x" * 2049))
        with pytest.raises(ValidationError) as exc_info:
            j.full_validate()
        assert "summary" in exc_info.value.message_dict


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLifecycleTimestamps:
    def test_default_timestamps_are_null(self):
        j = CollectionJob.objects.create(**_job_kwargs())
        assert j.enqueued_at is None
        assert j.started_at is None
        assert j.finished_at is None

    def test_timestamps_settable(self):
        now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)
        j = CollectionJob.objects.create(
            **_job_kwargs(),
            enqueued_at=now,
            started_at=now,
            finished_at=now,
        )
        assert j.enqueued_at == j.started_at == j.finished_at == now


# ---------------------------------------------------------------------------
# HAS_COLLECTION_JOB edge — req-tap-cares-collector-job-edge
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHasJobEdge:
    def test_has_job_edge_type_is_registered(self):
        from tap_grid.constraints import get_edge_type_constraints

        c = get_edge_type_constraints("HAS_COLLECTION_JOB")
        assert c is not None
        assert c.sources == {"collector"}
        assert c.targets == {"collection_job"}

    def test_outbound_declared_on_collector(self):
        assert any(
            entry.get("edges") and entry["edges"][0]["type"] == "HAS_COLLECTION_JOB"
            for entry in Collector.OUTBOUND_EDGES
        )

    def test_inbound_declared_on_collection_job(self):
        assert any(
            entry.get("edges") and entry["edges"][0]["type"] == "HAS_COLLECTION_JOB"
            for entry in CollectionJob.INBOUND_EDGES
        )

    def test_allowed_endpoints_create(self):
        from tap_grid.services import _create_edge_internal_for_test

        col = _make_collector("edge-ok")
        job = CollectionJob.objects.create(**_job_kwargs(name="edge-ok-job"))
        # HAS_COLLECTION_JOB is internal-only (req-grid-edge-internal): the trusted-internal path.
        edge = _create_edge_internal_for_test(col.entity, job.entity, "HAS_COLLECTION_JOB")
        assert edge is not None
        assert edge.edge_type == "HAS_COLLECTION_JOB"

    # Note: tap_grid uses Permission Union (constraints.py:419 validate_edge) —
    # an edge is allowed if EITHER node OR edge constraints permit it. Collector
    # has no INBOUND_EDGES, so a collector → collector HAS_COLLECTION_JOB edge is *not*
    # rejected even though the edge type's targets={"collection_job"} alone
    # would suggest it should be. Explicit rejection requires the target node
    # type to opt into INBOUND_EDGES constraints. The edge-type registration
    # is still the right place to document HAS_COLLECTION_JOB's intended source/target.
