"""The batch viewer surfaces a run's candidate record beside its completeness statement.

``req-grid-reconcile-candidates``: the record is derived and stored on the run's Batch;
the panel projects it (authority off — a display of what a falsifier would be handed) and
keeps "no record" distinct from "a record naming no surface".
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from tap_grid.batch import create_batch
from tap_grid.candidates import record_candidates
from tap_grid.completeness import record_completeness
from tap_web.panels.batch_viewer import DEFAULT_VAR_NAME, build_context


class _Panel:
    def __init__(self) -> None:
        self.entity_id = uuid.uuid4()
        self.config: dict[str, Any] = {"entity_id_var": DEFAULT_VAR_NAME}


def _request(batch_id: uuid.UUID) -> Any:
    request = MagicMock()
    request.GET = {DEFAULT_VAR_NAME: str(batch_id)}
    return request


def _run_with_statement() -> Any:
    now = timezone.now().isoformat()
    run = create_batch(source="test.batch_viewer.candidates")
    record_completeness(
        run,
        [
            {
                "relation": "repository.workflows",
                "subject": "repo:fixture",
                "interval": {"first": now, "last": now},
                "scope_authorized": True,
                "enumeration_complete": True,
                "source_consistent": "unknown",
                "admitted": True,
                "applied_batches": [],
                "reasons": {"source_consistent": "fixture", "applied": "nothing written"},
            }
        ],
    )
    run.refresh_from_db()
    return run


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestBatchViewerCandidates:
    def test_a_recorded_derivation_is_projected_per_surface(self) -> None:
        run = _run_with_statement()
        record_candidates(run, produced_batches=[])
        context = build_context(_Panel(), _request(run.entity_id))
        assert context["error_phase"] is None, context["error_message"]
        assert context["has_candidates"] is True
        [row] = context["candidates"]
        assert row["outcome"] == "skipped" and row["reason"].startswith("subject_unresolved")
        assert row["candidates"] == 0 and row["candidate_ids"] == ""
        assert context["counts"]["candidate_surfaces"] == 1 and context["counts"]["candidates"] == 0
        assert context["candidates_previous"] is None, "no previous run: withdrawal not observable"
        assert context["candidates_script_id"].endswith("-candidates")

    def test_no_record_is_distinct_from_an_empty_one(self) -> None:
        run = _run_with_statement()
        context = build_context(_Panel(), _request(run.entity_id))
        assert context["error_phase"] is None, context["error_message"]
        assert context["has_candidates"] is False and context["candidates"] == []
        assert context["counts"]["candidate_surfaces"] == 0
        assert context["has_completeness"] is True, "the statement is there; the derivation was never recorded"
