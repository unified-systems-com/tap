"""The batch viewer shows a run's edge authority record (``req-grid-reconcile-edge-authority-15``, Issue#
920 - tap): the counts, each held claim with the command that releases it, and each removal with its
outcome; "no record" stays distinct from a record that removed nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.template.loader import render_to_string

from tap_grid.candidates import record_candidates
from tap_grid.falsifiers import falsify_candidates, verdicts_of
from tap_grid.reconcile import EDGE_AUTHORITY_KEY, _store
from tap_grid.write_guard import unguarded_write
from tap_web.panels.batch_viewer import BatchViewerPanelType, build_context
from tap_web.tests.test_batch_viewer_candidates import _Panel, _request, _run_with_statement

SPEC = pytest.mark.spec("req-grid-reconcile-edge-authority-15")


def _held_record(edge_ids: list[str], *, released: dict[str, Any] | None = None) -> dict[str, Any]:
    claim = str(uuid.uuid4())
    held = "applied" if released else "held"
    return {
        "authority": "on",
        "counts": {"applied": len(edge_ids) if released else 0, "gone": 0, "held": 0 if released else len(edge_ids), "refused": 0, "rejected_stale": 0},
        "held_claims": [
            {
                "claim_event_id": claim,
                "batch": str(uuid.uuid4()),
                "edge_type": "NESTED_UNDER_PARENT__aws_core",
                "anchor": {"entity_type": "aws_account", "key": {"account_id": "004940046501"}},
                "anchor_entity_id": str(uuid.uuid4()),
                "direction": "outbound",
                "in_scope": len(edge_ids),
                "proposed": len(edge_ids),
                "released": released,
            }
        ],
        "entries": [
            {
                "edge_id": e,
                "edge_type": "NESTED_UNDER_PARENT__aws_core",
                "proposal_event_id": str(uuid.uuid4()),
                "claim_event_id": claim,
                "outcome": held,
                "error": None,
            }
            for e in edge_ids
        ],
    }


def _run_with_edge_authority(edge: dict[str, Any]) -> Any:
    """A run whose reconcile record carries ``edge`` — stored through the reconcile verb's own writer,
    so the record passes the verdicts schema exactly as an armed run's does."""
    run = _run_with_statement()
    record_candidates(run, produced_batches=[])
    run.refresh_from_db()
    falsify_candidates(run)
    record = verdicts_of(run)
    assert record is not None
    record[EDGE_AUTHORITY_KEY] = edge
    with unguarded_write():
        _store(run, record)
    return run


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestEdgeAuthorityProjection:
    @SPEC
    def test_a_held_claim_is_shown_with_the_command_that_releases_it(self) -> None:
        edges = [str(uuid.uuid4()) for _ in range(3)]
        run = _run_with_edge_authority(_held_record(edges))
        context = build_context(_Panel(), _request(run.entity_id))
        assert context["has_edge_authority"] is True and context["edge_authority_mode"] == "on"
        (held,) = context["edge_authority_held"]
        assert held["in_scope"] == 3 and held["released"] == ""
        assert held["release_command"] == (
            f"manage.py release_edge_authority_hold {run.entity_id} --claim {held['claim_event_id']} --as <operator>"
        )
        assert [e["outcome"] for e in context["edge_authority"]] == ["held"] * 3
        assert context["counts"]["edge_authority"] == 3
        assert context["edge_authority_script_id"].endswith("-edge_authority")
        html = render_to_string(BatchViewerPanelType.view, {"panel": _Panel(), **context})
        assert "Held:" in html and held["release_command"].replace("<", "&lt;").replace(">", "&gt;") in html

    @SPEC
    def test_a_released_claim_says_who_released_it_and_offers_no_command(self) -> None:
        edges = [str(uuid.uuid4()) for _ in range(3)]
        released = {"operator": "ops-arm_reconcile", "shell_user": "tap", "at": "2026-10-08T16:00:00+00:00"}
        run = _run_with_edge_authority(_held_record(edges, released=released))
        context = build_context(_Panel(), _request(run.entity_id))
        (held,) = context["edge_authority_held"]
        assert held["released"] == "ops-arm_reconcile at 2026-10-08T16:00:00+00:00" and held["release_command"] == ""
        assert [e["outcome"] for e in context["edge_authority"]] == ["applied"] * 3

    @SPEC
    def test_a_superseded_claim_names_what_superseded_it_and_offers_no_command(self) -> None:
        edges = [str(uuid.uuid4()) for _ in range(3)]
        record = _held_record(edges)
        newer = str(uuid.uuid4())
        record["held_claims"][0]["superseded_by"] = newer
        run = _run_with_edge_authority(record)
        context = build_context(_Panel(), _request(run.entity_id))
        (held,) = context["edge_authority_held"]
        assert (held["superseded_by"], held["release_command"]) == (newer, "")
        html = render_to_string(BatchViewerPanelType.view, {"panel": _Panel(), **context})
        assert "Superseded by a later complete read" in html and newer in html

    @SPEC
    def test_authority_off_says_how_many_proposals_stand_unapplied(self) -> None:
        off = {"authority": "off", "unapplied": 2, "counts": None, "held_claims": [], "entries": []}
        run = _run_with_edge_authority(off)
        context = build_context(_Panel(), _request(run.entity_id))
        assert (context["edge_authority_mode"], context["edge_authority_unapplied"]) == ("off", 2)
        assert "Authority off: 2 proposals recorded and not applied" in render_to_string(
            BatchViewerPanelType.view, {"panel": _Panel(), **context}
        )

    @SPEC
    def test_no_record_is_distinct_from_an_empty_one(self) -> None:
        run = _run_with_statement()
        context = build_context(_Panel(), _request(run.entity_id))
        assert context["has_edge_authority"] is False and context["edge_authority"] == []
