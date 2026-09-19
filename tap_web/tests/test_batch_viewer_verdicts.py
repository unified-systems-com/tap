"""The batch viewer surfaces a run's verdict record beside its candidate record
(``req-grid-reconcile-falsifier``, authority off): per candidate, the verdict and the write the
reconcile verb WOULD make; "no record" stays distinct from "a record judging nothing".
"""

from __future__ import annotations

import pytest

from tap_grid.candidates import record_candidates
from tap_grid.falsifiers import falsify_candidates
from tap_web.panels.batch_viewer import build_context
from tap_web.tests.test_batch_viewer_candidates import _Panel, _request, _run_with_statement


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestVerdictsProjection:
    def test_a_recorded_dispatch_is_projected_per_candidate(self) -> None:
        run = _run_with_statement()
        record_candidates(run, produced_batches=[])
        run.refresh_from_db()
        falsify_candidates(run)  # the fixture surface's subject is not a grid entity: zero candidates
        context = build_context(_Panel(), _request(run.entity_id))
        assert context["has_verdicts"] is True and context["verdicts"] == []
        assert context["counts"]["verdicts"] == 0 and context["counts"]["judged"] == 0
        assert context["verdicts_script_id"].endswith("-verdicts")

    def test_no_record_is_distinct_from_an_empty_one(self) -> None:
        run = _run_with_statement()
        context = build_context(_Panel(), _request(run.entity_id))
        assert context["has_verdicts"] is False and context["verdicts"] == []
