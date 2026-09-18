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

    @pytest.mark.spec("req-grid-service-delete-cascade-11")
    def test_the_cap_bounds_discovery_not_only_retirement(self, containment: None) -> None:
        """Codex on #569: children that share grandchildren must not enqueue the same ids
        once per parent, and the walk must refuse the moment it has SEEN more than the cap,
        not after it has tombstoned that many. Observed from outside the boundary: with a
        cap of 5, a root whose two children each contain the same ten grandchildren is
        refused at the first grandchild fetch, so the only tombstone written and rolled
        back is the root's own (the earlier walk wrote five nodes' worth first)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        s = _node(SOURCE, "root")
        children = [_node(TARGET, f"child-{i}") for i in range(2)]
        grandchildren = [_node(TARGET, f"shared-{i}") for i in range(10)]
        for child in children:
            create_edge(s, child, CONTAINS)
            for grandchild in grandchildren:
                create_edge(child, grandchild, NESTS)
        with override_settings(TAP_CASCADE_MAX_CLOSURE=5), CaptureQueriesContext(connection) as captured:
            result = delete_node(s.pk, cascade="contained")
        assert not result.success and result.errors[0].code == "cascade_closure_too_large"
        tombstones = [
            q["sql"] for q in captured.captured_queries if q["sql"].startswith("UPDATE") and "deleted_at" in q["sql"]
        ]
        assert len(tombstones) <= 2, f"{len(tombstones)} tombstone statements before refusal: {tombstones}"
        assert _live(s.pk) and all(_live(c.pk) for c in children) and all(_live(g.pk) for g in grandchildren)

    def _convergent(self) -> dict[str, Any]:
        """S contains A and B; A and B both contain X1..X3; B alone also contains Y.
        Seven nodes. The walk reaches B after A has already discovered the three X's."""
        s, a, b = _node(SOURCE, "root"), _node(TARGET, "a"), _node(TARGET, "b")
        shared = [_node(TARGET, f"x-{i}") for i in range(3)]
        y = _node(TARGET, "y")
        create_edge(s, a, CONTAINS)
        create_edge(s, b, CONTAINS)
        for x in shared:
            create_edge(a, x, NESTS)
            create_edge(b, x, NESTS)
        create_edge(b, y, NESTS)
        return {"s": s, "a": a, "b": b, "shared": shared, "y": y}

    @pytest.mark.spec("req-grid-service-delete-cascade-1")
    @pytest.mark.spec("req-grid-service-delete-cascade-11")
    def test_already_discovered_children_cannot_hide_an_unseen_one(self, containment: None) -> None:
        """Codex on #569 round 2: with the cap at 6 and six nodes already discovered when the
        walk reaches B, the headroom slice is one row. If the three already-seen X's could
        fill that slice, Y would never be discovered and the walk would "succeed" leaving
        part of the declared subtree live. Discovered nodes are excluded in the query, so
        the one row is Y, discovery hits seven, and the walk is refused — every time, not
        depending on row order."""
        g = self._convergent()
        with override_settings(TAP_CASCADE_MAX_CLOSURE=6):
            result = delete_node(g["s"].pk, cascade="contained")
        assert not result.success and result.errors[0].code == "cascade_closure_too_large"
        assert _live(g["s"].pk) and _live(g["y"].pk) and all(_live(x.pk) for x in g["shared"])

    @pytest.mark.spec("req-grid-service-delete-cascade-1")
    def test_the_convergent_subtree_retires_whole_when_it_fits(self, containment: None) -> None:
        g = self._convergent()
        with override_settings(TAP_CASCADE_MAX_CLOSURE=7):
            result = delete_node(g["s"].pk, cascade="contained")
        assert result.success, result.errors
        assert not _live(g["y"].pk) and not any(_live(x.pk) for x in g["shared"])
        for x in g["shared"]:
            assert BatchEvent.objects.filter(entity_id=x.pk, event_type=BatchEventType.DELETE).count() == 1

    @pytest.mark.spec("req-grid-service-delete-cascade-11")
    @pytest.mark.spec("req-grid-service-delete-cascade-13")
    def test_a_self_loop_cannot_consume_the_overflow_witness(self, containment: None) -> None:
        """Issue# 572 - tap: cap 2; R contains R, A and B. Before discovered nodes were
        excluded in the query, a legal row order could return R (already visited) and A in
        the two-row slice, drop B, and report success with B live — a partial retirement of
        an over-cap closure. The root is discovered before its own fetch, so the self-loop
        is excluded from the query, the slice is A and B, discovery hits three, and the
        walk is refused with nothing changed — whatever order the rows come back in."""
        r = _node(TARGET, "R")
        a, b = _node(TARGET, "A"), _node(TARGET, "B")
        loop = create_edge(r, r, NESTS)
        create_edge(r, a, NESTS)
        create_edge(r, b, NESTS)
        before = {e.pk: e.version for e in Entity.objects.filter(pk__in=[r.pk, a.pk, b.pk])}
        events_before = BatchEvent.objects.count()
        with override_settings(TAP_CASCADE_MAX_CLOSURE=2):
            result = delete_node(r.pk, cascade="contained")
        assert not result.success and result.errors[0].code == "cascade_closure_too_large"
        assert _live(r.pk) and _live(a.pk) and _live(b.pk)
        assert {e.pk: e.version for e in Entity.objects.filter(pk__in=[r.pk, a.pk, b.pk])} == before
        assert Edge.all_objects.get(entity_id=loop.entity_id).entity.deleted_at is None
        assert BatchEvent.objects.count() == events_before, "a refused walk records nothing"

    @pytest.mark.spec("req-grid-service-delete-cascade-13")
    def test_a_self_loop_at_the_cap_retires_the_closure_once(self, containment: None) -> None:
        r = _node(TARGET, "R")
        a, b = _node(TARGET, "A"), _node(TARGET, "B")
        create_edge(r, r, NESTS)
        create_edge(r, a, NESTS)
        create_edge(r, b, NESTS)
        with override_settings(TAP_CASCADE_MAX_CLOSURE=3):
            result = delete_node(r.pk, cascade="contained")
        assert result.success, result.errors
        assert not _live(r.pk) and not _live(a.pk) and not _live(b.pk)
        for node in (r, a, b):
            assert BatchEvent.objects.filter(entity_id=node.pk, event_type=BatchEventType.DELETE).count() == 1

    @pytest.mark.spec("req-grid-service-delete-cascade-14")
    def test_inbound_reference_edges_and_both_endpoints_record_once(self, containment: None) -> None:
        """Issue# 573 - tap: an INBOUND reference edge into a cascaded child is a consequence
        of that child; an edge whose both endpoints retire (S contains T1) records exactly
        one unlink event, not one per endpoint."""
        g = self._tree()
        outsider = _node(SOURCE, "outsider")
        inbound = create_edge(outsider, g["t1"], REFERS)  # outsider → T1, T1 is cascaded
        assert delete_node(g["s"].pk, cascade="contained", reason="scope_withdrawn").success
        assert _live(outsider.pk)
        inbound_events = BatchEvent.objects.filter(entity_id=inbound.entity_id, event_type=BatchEventType.UNLINK)
        assert inbound_events.count() == 1
        assert inbound_events.get().metadata["consequence_of"] == str(g["t1"].pk)
        for edge in (g["contains"], g["nests"], g["refers"]):
            assert (
                BatchEvent.objects.filter(entity_id=edge.entity_id, event_type=BatchEventType.UNLINK).count() == 1
            ), f"edge {edge.entity_id} recorded more than once"

    @pytest.mark.spec("req-grid-service-delete-cascade-1")
    def test_a_cascade_value_outside_the_set_is_refused_before_any_write(self, containment: None) -> None:
        """Codex on #569: a typo must not fall through to "none" and tombstone the root while
        its contained children stay live. Both doors: the wrapper and a raw WriteOperation."""
        from tap_grid.services import write_batch

        g = self._tree()
        result = delete_node(g["s"].pk, cascade="containned")  # type: ignore[arg-type]
        assert not result.success and result.errors[0].code == "validation_error"
        raw = write_batch([WriteOperation(verb="delete_node", target=g["s"].pk, cascade="containned")])  # type: ignore[arg-type]
        assert not raw.success
        assert any(e.code == "validation_error" for r in raw.results for e in r.errors) or any(
            e.code == "validation_error" for e in raw.errors
        )
        assert _live(g["s"].pk) and _live(g["t1"].pk) and _live(g["t3"].pk)
        assert Edge.all_objects.get(entity_id=g["contains"].entity_id).entity.deleted_at is None

    @pytest.mark.spec("req-grid-service-delete-cascade-14")
    def test_edges_ended_by_the_walk_record_provenance_too(self, containment: None) -> None:
        """Codex on #569: -14 says every node AND edge the walk retires records its parent.
        The containment edge and the reference edge are consequences of the root; the
        nesting edge is a consequence of the child it hangs from."""
        g = self._tree()
        assert delete_node(
            g["s"].pk, cascade="contained", reason="scope_withdrawn", metadata={"scope": "run-7"}
        ).success

        def unlink(edge: Any) -> dict[str, Any]:
            event = BatchEvent.objects.filter(entity_id=edge.entity_id, event_type=BatchEventType.UNLINK).first()
            assert event is not None, f"no unlink event for {edge.entity_id}"
            return dict(event.metadata)

        for edge, parent in ((g["contains"], g["s"]), (g["refers"], g["s"]), (g["nests"], g["t1"])):
            meta = unlink(edge)
            assert meta["reason"] == "cascaded"
            assert meta["consequence_of"] == str(parent.pk)
            assert meta["cascade_root"] == str(g["s"].pk)
            assert meta["root_reason"] == "scope_withdrawn"
            assert meta["scope"] == "run-7", "the root's evidence is inherited by its edges"

    @pytest.mark.spec("req-grid-service-delete-cascade-14")
    def test_a_plain_delete_keeps_its_pre_existing_edge_shape(self, containment: None) -> None:
        """Without a cascade the endpoint rule ends the edges as before: no per-edge event."""
        g = self._tree()
        assert delete_node(g["s"].pk).success
        assert not BatchEvent.objects.filter(
            entity_id=g["contains"].entity_id, event_type=BatchEventType.UNLINK
        ).exists()

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
