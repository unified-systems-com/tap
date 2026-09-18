"""Reason and metadata on delete, and the contained cascade.

``req-grid-service-delete-reason``: a tombstone records a closed-vocabulary reason and a
structured payload in its BatchEvent; an omitted reason is ``unspecified``, never
``operator``.

``req-grid-service-delete-cascade``: ``delete_node(..., cascade="contained")`` walks the
model's dedicated ``CONTAINMENT_EDGES`` declaration recursively, in one transaction, capped
and cycle-safe; a refusal on any child rolls the whole subtree back; reference edges are
ended and their far nodes left alone.

The fixture graph uses ``grid_fixtures``' constrained types, whose permitted edges already
include a self-nesting link (``NESTING_LINK__grid_fixtures``) and two source→target links.
``CONTAINMENT_EDGES`` is declared on them per test via monkeypatch — the plugin's own
declarations are phase 3's — which also exercises the rule that containment is a subset of
permission.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from tap_grid.models import BaseModel, BatchEvent, BatchEventType, Edge, Entity
from tap_grid.service_types import DELETE_REASONS, UNSPECIFIED_REASON, WriteOperation
from tap_grid.services import create_edge, create_node, delete_edge_by_entity, delete_node

SOURCE = "grid_fixtures__constrained_source"
TARGET = "grid_fixtures__constrained_target"
CONTAINS = "CONSTRAINED_LINK__grid_fixtures"  # declared containment in these tests
REFERS = "ALT_LINK__grid_fixtures"  # left as a reference
NESTS = "NESTING_LINK__grid_fixtures"  # target → target, declared containment in these tests


def _node(entity_type: str, name: str) -> Entity:
    result = create_node(entity_type, {"name": name})
    assert result.success, result.errors
    assert result.entity_id is not None
    return Entity.objects.get(pk=result.entity_id)


def _live(entity_id: uuid.UUID) -> bool:
    return Entity.objects.get(pk=entity_id).deleted_at is None


def _delete_event(entity_id: uuid.UUID) -> BatchEvent:
    event = (
        BatchEvent.objects.filter(entity_id=entity_id, event_type=BatchEventType.DELETE).order_by("-timestamp").first()
    )
    assert event is not None, f"no delete event for {entity_id}"
    return event


@pytest.fixture
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.grid_fixtures.models import ConstrainedSource, ConstrainedTarget

    monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (CONTAINS,), raising=False)
    monkeypatch.setattr(ConstrainedTarget, "CONTAINMENT_EDGES", (NESTS,), raising=False)


# ---------------------------------------------------------------------------
# req-grid-service-delete-reason
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteReason:
    @pytest.mark.spec("req-grid-service-delete-reason-1")
    def test_reason_and_metadata_reach_the_batch_event(self) -> None:
        node = _node(SOURCE, "Numenor")
        result = delete_node(
            node.pk,
            reason="dropped_from_observation",
            metadata={"evidence": "complete_listing", "scope": "run-42"},
        )
        assert result.success, result.errors
        meta = _delete_event(node.pk).metadata
        assert meta["reason"] == "dropped_from_observation"
        assert meta["evidence"] == "complete_listing"
        assert meta["scope"] == "run-42"

    @pytest.mark.spec("req-grid-service-delete-reason-4")
    def test_omitted_reason_is_unspecified_never_operator(self) -> None:
        node = _node(SOURCE, "Gondolin")
        assert delete_node(node.pk).success
        assert _delete_event(node.pk).metadata["reason"] == UNSPECIFIED_REASON
        assert UNSPECIFIED_REASON != "operator"
        assert WriteOperation(verb="delete_node").reason is None, "the operation carries no default reason"

    @pytest.mark.spec("req-grid-service-delete-reason-3")
    def test_reason_outside_the_vocabulary_is_refused_before_any_write(self) -> None:
        node = _node(SOURCE, "Beleriand")
        result = delete_node(node.pk, reason="because")
        assert not result.success
        assert result.errors[0].code == "invalid_reason"
        assert _live(node.pk)
        assert not BatchEvent.objects.filter(entity_id=node.pk, event_type=BatchEventType.DELETE).exists()

    @pytest.mark.spec("req-grid-service-delete-reason-3")
    def test_vocabulary_is_the_declared_one(self) -> None:
        assert DELETE_REASONS == {
            "dropped_from_observation",
            "scope_withdrawn",
            "cascaded",
            "resolved",
            "operator",
            "grift_import",
            "unspecified",
        }

    @pytest.mark.spec("req-grid-service-delete-reason-1")
    @pytest.mark.spec("req-grid-service-delete-reason-3")
    def test_raw_write_batch_cannot_bypass_the_vocabulary(self) -> None:
        """Codex and Grok on #568: the check lives in the pipeline, not only in the wrappers."""
        from tap_grid.services import write_batch

        node = _node(SOURCE, "Angband")
        result = write_batch([WriteOperation(verb="delete_node", target=node.pk, reason="because")])
        assert not result.success
        assert any(e.code == "invalid_reason" for r in result.results for e in r.errors) or any(
            e.code == "invalid_reason" for e in result.errors
        )
        assert _live(node.pk)

    @pytest.mark.spec("req-grid-service-delete-reason-1")
    def test_unrecordable_metadata_is_refused_not_dropped(self) -> None:
        """Codex on #568: metadata that cannot be stored must not become a tombstone with no audit row."""
        node = _node(SOURCE, "Utumno")
        result = delete_node(node.pk, reason="operator", metadata={"when": object()})  # not JSON
        assert not result.success
        assert result.errors[0].code == "invalid_reason"
        assert _live(node.pk)

    @pytest.mark.spec("req-grid-service-delete-reason-1")
    def test_provenance_failure_refuses_the_tombstone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fail-closed: a retirement whose audit record cannot be written is not applied."""
        import tap_grid.batch as batch_module

        node = _node(SOURCE, "Dol Guldur")

        def _boom(**kwargs: Any) -> None:
            raise RuntimeError("audit store down")

        monkeypatch.setattr(batch_module, "record_batch_event", _boom)
        result = delete_node(node.pk, reason="operator")
        assert not result.success
        assert _live(node.pk)

    @pytest.mark.spec("req-grid-service-delete-reason-1")
    def test_edge_delete_records_reason_too(self) -> None:
        a, b = _node(SOURCE, "Bree"), _node(TARGET, "Rivendell")
        edge = create_edge(a, b, CONTAINS)
        result = delete_edge_by_entity(edge.entity_id, reason="operator", metadata={"ticket": "T-1"})
        assert result.success, result.errors
        event = BatchEvent.objects.filter(entity_id=edge.entity_id, event_type=BatchEventType.UNLINK).first()
        assert event is not None
        assert event.metadata["reason"] == "operator"
        assert event.metadata["ticket"] == "T-1"


# ---------------------------------------------------------------------------
# req-grid-service-delete-cascade
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContainedCascade:
    def _tree(self) -> dict[str, Any]:
        """S ──CONTAINS──▶ T1 ──NESTS──▶ T3 ;  S ──REFERS──▶ T2  (T2 is a reference far node)."""
        s = _node(SOURCE, "repository")
        t1 = _node(TARGET, "workflow")
        t2 = _node(TARGET, "ruleset")
        t3 = _node(TARGET, "job")
        e_contains = create_edge(s, t1, CONTAINS)
        e_refers = create_edge(s, t2, REFERS)
        e_nests = create_edge(t1, t3, NESTS)
        return {"s": s, "t1": t1, "t2": t2, "t3": t3, "contains": e_contains, "refers": e_refers, "nests": e_nests}

    @pytest.mark.spec("req-grid-service-delete-cascade-1")
    def test_containment_followed_references_ended_far_nodes_kept(self, containment: None) -> None:
        g = self._tree()
        result = delete_node(g["s"].pk, cascade="contained", reason="dropped_from_observation")
        assert result.success, result.errors
        # The contained subtree retires: S, T1 and (through T1's nesting) T3.
        assert not _live(g["s"].pk) and not _live(g["t1"].pk) and not _live(g["t3"].pk)
        # The reference far node stays live; its edge is ended by the endpoint rule.
        assert _live(g["t2"].pk)
        assert Edge.all_objects.get(entity_id=g["refers"].entity_id).entity.deleted_at is not None
        assert Edge.all_objects.get(entity_id=g["contains"].entity_id).entity.deleted_at is not None

    @pytest.mark.spec("req-grid-service-delete-cascade-1")
    def test_without_cascade_only_the_target_and_its_edges_retire(self, containment: None) -> None:
        g = self._tree()
        assert delete_node(g["s"].pk).success
        assert not _live(g["s"].pk)
        assert _live(g["t1"].pk) and _live(g["t2"].pk) and _live(g["t3"].pk)

    @pytest.mark.spec("req-grid-service-delete-cascade-2")
    def test_undeclared_edge_type_is_never_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No CONTAINMENT_EDGES on the source: CONSTRAINED_LINK is a reference like any other."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (), raising=False)
        g = self._tree()
        assert delete_node(g["s"].pk, cascade="contained").success
        assert not _live(g["s"].pk)
        assert _live(g["t1"].pk) and _live(g["t3"].pk)

    @pytest.mark.spec("req-grid-service-delete-cascade-14")
    def test_provenance_names_the_parent_and_the_root(self, containment: None) -> None:
        g = self._tree()
        delete_node(g["s"].pk, cascade="contained", reason="scope_withdrawn", metadata={"scope": "run-7"})
        root = _delete_event(g["s"].pk).metadata
        assert root["reason"] == "scope_withdrawn" and root["scope"] == "run-7"
        child = _delete_event(g["t1"].pk).metadata
        assert child["reason"] == "cascaded"
        assert child["consequence_of"] == str(g["s"].pk)
        assert child["cascade_root"] == str(g["s"].pk)
        assert child["root_reason"] == "scope_withdrawn"
        assert child["scope"] == "run-7", "the parent's evidence is inherited"
        grandchild = _delete_event(g["t3"].pk).metadata
        assert grandchild["consequence_of"] == str(g["t1"].pk)
        assert grandchild["cascade_root"] == str(g["s"].pk)

    @pytest.mark.spec("req-grid-service-delete-cascade-13")
    def test_cycle_terminates_and_retires_each_node_once(self, containment: None) -> None:
        t1, t3 = _node(TARGET, "a"), _node(TARGET, "b")
        create_edge(t1, t3, NESTS)
        create_edge(t3, t1, NESTS)
        result = delete_node(t1.pk, cascade="contained")
        assert result.success, result.errors
        assert not _live(t1.pk) and not _live(t3.pk)
        assert BatchEvent.objects.filter(entity_id=t3.pk, event_type=BatchEventType.DELETE).count() == 1

    @pytest.mark.spec("req-grid-service-delete-cascade-11")
    def test_over_the_cap_refuses_and_writes_nothing(self, containment: None) -> None:
        g = self._tree()  # S, T1, T3 = three nodes in the contained subtree
        with override_settings(TAP_CASCADE_MAX_CLOSURE=2):
            result = delete_node(g["s"].pk, cascade="contained")
        assert not result.success
        assert result.errors[0].code == "cascade_closure_too_large"
        assert _live(g["s"].pk) and _live(g["t1"].pk) and _live(g["t3"].pk)
        assert Edge.all_objects.get(entity_id=g["contains"].entity_id).entity.deleted_at is None

    @pytest.mark.spec("req-grid-service-delete-cascade-4")
    def test_refusal_on_a_child_rolls_the_whole_cascade_back(
        self, containment: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every child goes through the same pipeline checks as any delete; an
        INTERNAL_ONLY child is refused there, and the target stays live too."""
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        g = self._tree()
        monkeypatch.setattr(ConstrainedTarget, "INTERNAL_ONLY", True, raising=False)
        result = delete_node(g["s"].pk, cascade="contained")
        assert not result.success
        assert result.errors[0].code == "unsupported_operation"
        assert "refused at" in result.errors[0].message
        assert _live(g["s"].pk) and _live(g["t1"].pk) and _live(g["t3"].pk)
        assert Edge.all_objects.get(entity_id=g["contains"].entity_id).entity.deleted_at is None

    @pytest.mark.spec("req-grid-service-delete-cascade-3")
    @pytest.mark.spec("req-grid-service-delete-cascade-13")
    def test_a_chain_longer_than_the_python_stack_still_walks(self, containment: None) -> None:
        """Grok on #568: the walk is iterative, so depth is bounded by the cap, not the stack."""
        import sys

        depth = sys.getrecursionlimit() + 100
        head = _node(TARGET, "link-0")
        prev = head
        for i in range(1, depth):
            nxt = _node(TARGET, f"link-{i}")
            create_edge(prev, nxt, NESTS)
            prev = nxt
        with override_settings(TAP_CASCADE_MAX_CLOSURE=depth + 10):
            result = delete_node(head.pk, cascade="contained")
        assert result.success, result.errors
        assert not _live(head.pk) and not _live(prev.pk)

    @pytest.mark.spec("req-grid-service-delete-cascade-11")
    def test_child_fetch_is_bounded_by_the_caps_headroom(self, containment: None) -> None:
        """Codex on #568: a high-fan-out node must not materialise its whole neighbourhood
        before the cap is noticed. Observed from outside the service boundary — the SQL the
        walk issues carries the bound — rather than by spying on a private helper."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        s = _node(SOURCE, "fan")
        for i in range(6):
            create_edge(s, _node(TARGET, f"leaf-{i}"), CONTAINS)
        with override_settings(TAP_CASCADE_MAX_CLOSURE=3), CaptureQueriesContext(connection) as captured:
            result = delete_node(s.pk, cascade="contained")
        assert not result.success and result.errors[0].code == "cascade_closure_too_large"
        child_fetches = [
            q["sql"] for q in captured.captured_queries if "to_entity_id" in q["sql"] and "edge_type" in q["sql"]
        ]
        assert child_fetches, "no child fetch observed"
        assert all("LIMIT" in sql for sql in child_fetches), child_fetches
        assert all(int(sql.rsplit("LIMIT", 1)[1].split()[0]) <= 3 for sql in child_fetches), child_fetches

    @pytest.mark.spec("req-grid-service-delete-cascade-3")
    def test_rerun_skips_already_retired_children(self, containment: None) -> None:
        g = self._tree()
        assert delete_node(g["t1"].pk, cascade="contained").success  # T1 and T3 gone
        assert delete_node(g["s"].pk, cascade="contained").success  # S; T1 already retired
        assert BatchEvent.objects.filter(entity_id=g["t1"].pk, event_type=BatchEventType.DELETE).count() == 1


class TestContainmentDeclaration:
    """req-grid-service-delete-cascade-12: a dedicated declaration, a subset of permission."""

    @pytest.mark.spec("req-grid-service-delete-cascade-12")
    def test_base_declares_nothing(self) -> None:
        assert BaseModel.CONTAINMENT_EDGES == ()

    @pytest.mark.spec("req-grid-service-delete-cascade-12")
    def test_outbound_edges_carry_no_cascade_semantics(self) -> None:
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        for entry in ConstrainedSource.OUTBOUND_EDGES:
            for edge in entry.get("edges", []):
                assert set(edge) == {"type"}, f"OUTBOUND_EDGES entry carries more than a type: {edge}"

    @pytest.mark.spec("req-grid-service-delete-cascade-12")
    def test_containment_outside_permission_is_refused_at_class_creation(self) -> None:
        from tap.pytest_harness import isolated_registry

        with isolated_registry(), pytest.raises(ImproperlyConfigured, match="CONTAINMENT_EDGES"):

            class _Leaky(BaseModel):
                ENTITY_TYPE = "leaky_test_type"
                NATURAL_KEY = ("name",)
                FIELD_CRUD_SCHEMA = {"name": {"type": "string"}}
                OUTBOUND_EDGES = [{"nodes": [{"type": "leaky_test_type"}], "edges": [{"type": "PERMITTED"}]}]
                CONTAINMENT_EDGES = ("NOT_PERMITTED",)

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
