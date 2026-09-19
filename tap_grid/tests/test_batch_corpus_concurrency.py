"""The batch playground's timing family (Issue# 603 - tap): two-writer interleavings the JSON
cannot express, made deterministic on the real database with the cascade corpus's harness
(``tap_grid.cascade_corpus.timing``): a holder takes a lock — the identity advisory lock a ref
resolution takes, or a row lock — and the contending import is observed blocked on it by pid
before the holder does its work and commits. Every case asserts the same things a shaped
scenario does: exact rows and versions, nothing else written, event deltas, result shape.

The second pass (Issue# 613 - tap; George, 2026-09-18: "should be fine with transactions, but
you never know till you test") adds the write × delete schedules in PostgreSQL isolation-spec
style (``insert-conflict-specconflict.spec``: a controller holds locks and releases them in a
named order, so every permutation is a deterministic interleaving, never a sleep): write/write on
one id, write then delete and delete then write, delete/delete, edge create against endpoint
delete in both orders, a cascade during a subtree write, and a delete section against an upsert
of the same id in two batches. Each states its acceptable serial outcomes and, after both
writers finish, asserts the two invariants — no live edge has a tombstoned endpoint, and no
tombstone is ever re-written.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest
from django.db import transaction

from tap_grid.cascade_corpus.timing import (
    JOIN_SECONDS,
    NESTS,
    NODE,
    contains,
    contend,
    event_counts,
    event_delta,
    finish,
    hold_lock_then,
    in_thread,
    live_edges_onto_tombstones,
    node,
    rewritten_tombstones,
    snapshot,
    wait_until_blocked_by,
)
from tap_grid.grift import grift_import
from tap_grid.models import Batch, BatchEventType, Edge, Entity
from tap_grid.services import create_node, delete_node, replace_node, resolve_identity
from tap_web.models import Panel

pytestmark = [pytest.mark.batch_corpus, pytest.mark.django_db(transaction=True)]

VIEW = "tap_web/panel_error.html"
#: The write pipeline decides the tombstone check on an unlocked read for a plain replace, so a
#: row tombstoned while the replace waited is still written (Issue# 611 - tap). Recognised by
#: its exact shape, never by "the test failed".
TOMBSTONE_RACE = "unified-systems-com/tap#611"


def _wrote_onto_the_tombstone(result: Any, row: Entity, doc: dict[str, Any], name_from_bundle: str) -> bool:
    """Issue# 611 - tap's shape: the batch committed, the row is tombstoned AND carries the
    bundle's content at version 3 (the delete's bump plus the replace's)."""
    return (
        result.success
        and row.deleted_at is not None
        and row.version == 3
        and row.name == name_from_bundle
        and Batch.all_objects.filter(entity_id=_batch_id(doc)).exists()
    )


def _expect_replace_refused_on_the_tombstone(
    result: Any, a_id: uuid.UUID, doc: dict[str, Any], name_from_bundle: str, events_before: Any, before: Any
) -> None:
    """The ruled outcome, or the one known defect shape as a verified expected failure."""
    row = Entity.objects.get(pk=a_id)
    if _wrote_onto_the_tombstone(result, row, doc, name_from_bundle):
        delta = event_delta(events_before, event_counts())
        assert delta == {(a_id, "delete"): 1, (a_id, "update"): 1}, delta
        pytest.xfail(
            f"pending {TOMBSTONE_RACE} — verified in-body: the replace landed on the tombstone (version 3, update event)"
        )
    assert not result.success and [(e.code, e.path) for e in result.errors] == [
        ("execution_failed", "$.batches[0].nodes[0]")
    ]
    assert not Batch.all_objects.filter(entity_id=_batch_id(doc)).exists()
    assert row.deleted_at is not None and row.version == 2 and row.name != name_from_bundle
    assert event_delta(events_before, event_counts()) == {(a_id, "delete"): 1}
    assert _one_delta(before, snapshot()) == set()


def _panel(slug: str, name: str) -> dict[str, Any]:
    return {"name": name, "slug": slug, "description": "", "view": VIEW}


def _doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _doc_with(nodes=nodes)


def _doc_with(
    nodes: tuple[dict[str, Any], ...] = (),
    edges: tuple[dict[str, Any], ...] = (),
    deletes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bid = str(uuid.uuid7())
    container: dict[str, Any] = {
        "batch_entity": {"entity_id": bid, "entity_type": "batch", "name": "timing", "dimensions": {}},
        "batch_node": {
            "name": "timing",
            "description": "",
            "description_json": None,
            "source": "batch_corpus",
            "metadata": {},
        },
        "nodes": list(nodes),
        "edges": list(edges),
    }
    if deletes is not None:
        container["deletes"] = deletes
    return {"metadata": {"grift_version": "0"}, "_reserved": {}, "batches": [container]}


def _edge(edge_id: str, from_id: str, to_id: str) -> dict[str, Any]:
    return {
        "entity": {"entity_id": edge_id, "entity_type": "edge", "dimensions": {}},
        "edge": {
            "from_entity_id": from_id,
            "to_entity_id": to_id,
            "edge_type": "PG_LINKS__grid_fixtures",
            "properties": {},
        },
    }


def _delete_section(entity_id: str, entity_type: str = NODE, on_tombstoned: str = "ignore") -> dict[str, Any]:
    return {
        "on_missing": "error",
        "on_tombstoned": on_tombstoned,
        "edges": [],
        "nodes": [{"entity_id": entity_id, "entity_type": entity_type, "reason": "no longer observed"}],
    }


@pytest.fixture(autouse=True)
def _no_live_edge_onto_a_tombstone() -> Any:
    """The first invariant, after every case in this module: at no committed state does a live
    edge have a tombstoned endpoint (Issue# 609 - tap, ruled 2026-09-18). A case pending on the
    ruling recognises the violation itself and clears it before this runs."""
    yield
    onto = live_edges_onto_tombstones()
    assert onto == [], f"live edges onto tombstones after the case: {onto}"


def _ref_bundle(slug: str, name: str) -> dict[str, Any]:
    return _doc(
        {"entity": {"ref": "it", "entity_type": "panel", "name": name, "dimensions": {}}, "node": _panel(slug, name)}
    )


def _id_bundle(
    entity_id: str, entity_type: str, payload: dict[str, Any], expected_version: int | None = None
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "name": payload["name"],
        "dimensions": {},
    }
    if expected_version is not None:
        envelope["entity_expected_version"] = expected_version
    return _doc({"entity": envelope, "node": payload})


def _batch_id(doc: dict[str, Any]) -> str:
    return str(doc["batches"][0]["batch_entity"]["entity_id"])


def _one_delta(
    before: dict[uuid.UUID, tuple[bool, int]], after: dict[uuid.UUID, tuple[bool, int]], *known: uuid.UUID
) -> set[uuid.UUID]:
    """Ids that appeared during the case, minus the ones the case expects."""
    return set(after) - set(before) - set(known)


def _hold_identity_then(slug: str, locked: threading.Event, go: threading.Event, then: Any) -> Any:
    """In one transaction: take the identity lock a ref resolution on ``slug`` takes, say so,
    wait for the signal, run ``then``, commit."""
    with transaction.atomic():
        resolve_identity("panel", {"slug": slug})
        locked.set()
        if not go.wait(JOIN_SECONDS):
            raise AssertionError("the test never released the lock holder")
        return then()


def _import_blocked_by_holder(holder_body: Any, contender_doc: dict[str, Any]) -> tuple[Any, Any]:
    locked, go = threading.Event(), threading.Event()
    holder = in_thread(lambda: holder_body(locked, go))
    if not locked.wait(JOIN_SECONDS):
        raise AssertionError("the holder never took its lock")
    other = in_thread(lambda: grift_import(contender_doc))
    try:
        wait_until_blocked_by(other[1], holder[1])
    finally:
        go.set()
    finish(holder, other)
    return holder[1].value, other[1].value


@pytest.mark.spec("req-grid-batch-corpus-timing-1")
@pytest.mark.spec("req-grid-batch-corpus-timing-2")
class TestTiming:
    def test_same_ref_bundle_the_lock_serialises_and_the_second_finds_the_first(self) -> None:
        """The holder resolves the object first and creates it while the contender waits on the
        identity lock; the contender then finds the row: one panel, one create, one update."""
        before, events_before = snapshot(), event_counts()
        first_doc, second_doc = _ref_bundle("serial", "First"), _ref_bundle("serial", "Second")
        first, second = _import_blocked_by_holder(
            lambda locked, go: _hold_identity_then("serial", locked, go, lambda: grift_import(first_doc)), second_doc
        )
        assert first.success and second.success, (first.errors, second.errors)
        row_id = first.imported_batches[0].resolved_refs["it"]
        assert second.imported_batches[0].resolved_refs["it"] == row_id, "the second found the first's row"
        assert [u.entity_id for u in second.imported_batches[0].upserted_entities] == [row_id]
        assert Panel.objects.filter(slug="serial").count() == 1
        row = Entity.objects.get(pk=uuid.UUID(row_id))
        assert row.deleted_at is None and row.version == 2 and row.name == "Second"
        delta = event_delta(events_before, event_counts())
        assert delta[(row.pk, "create")] == 1 and delta[(row.pk, "update")] == 1
        after = snapshot()
        assert Batch.objects.filter(entity_id__in=[_batch_id(first_doc), _batch_id(second_doc)]).count() == 2
        assert (
            _one_delta(before, after, row.pk, uuid.UUID(_batch_id(first_doc)), uuid.UUID(_batch_id(second_doc)))
            == set()
        )

    def test_same_ref_bundle_free_race_makes_one_row(self) -> None:
        """No hold: whichever writer wins the identity lock creates; the other replaces."""
        before, events_before = snapshot(), event_counts()
        a_doc, b_doc = _ref_bundle("race", "A"), _ref_bundle("race", "B")
        a = in_thread(lambda: grift_import(a_doc))
        b = in_thread(lambda: grift_import(b_doc))
        finish(a, b)
        ra, rb = a[1].value, b[1].value
        assert ra.success and rb.success, (ra.errors, rb.errors)
        row_id = ra.imported_batches[0].resolved_refs["it"]
        assert rb.imported_batches[0].resolved_refs["it"] == row_id
        assert Panel.objects.filter(slug="race").count() == 1
        row = Entity.objects.get(pk=uuid.UUID(row_id))
        assert row.version == 2 and row.name in {"A", "B"}
        delta = event_delta(events_before, event_counts())
        assert delta[(row.pk, "create")] == 1 and delta[(row.pk, "update")] == 1
        assert _one_delta(before, snapshot(), row.pk, uuid.UUID(_batch_id(a_doc)), uuid.UUID(_batch_id(b_doc))) == set()

    def test_a_row_tombstoned_under_a_waiting_id_replace_fails_that_batch(self) -> None:
        """The contender routed to replace because the row was live; by the time it holds the
        row, the holder has tombstoned it. The tombstone is terminal: the batch must fail and write
        nothing — today it writes onto the tombstone (Issue# 611 - tap), verified in-body."""
        created = create_node("grid_fixtures__node", {"name": "A"})
        assert created.success and created.entity_id is not None
        a_id = uuid.UUID(str(created.entity_id))
        before, events_before = snapshot(), event_counts()
        doc = _id_bundle(str(a_id), "grid_fixtures__node", {"name": "A, replaced"})
        deleted, result = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(a_id, locked, go, lambda: delete_node(a_id, reason="operator")), doc
        )
        assert deleted.success
        _expect_replace_refused_on_the_tombstone(result, a_id, doc, "A, replaced", events_before, before)

    def test_a_row_bumped_under_a_waiting_versioned_replace_conflicts(self) -> None:
        """OCC under contention: the holder's replace moves the row to version 2 while the
        contender, expecting 1, waits on the row lock; the check runs against the committed row."""
        created = create_node("grid_fixtures__node", {"name": "A"})
        assert created.success and created.entity_id is not None
        a_id = uuid.UUID(str(created.entity_id))
        before, events_before = snapshot(), event_counts()
        doc = _id_bundle(str(a_id), "grid_fixtures__node", {"name": "A, from the bundle"}, expected_version=1)
        bumped, result = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(
                a_id, locked, go, lambda: replace_node(a_id, {"name": "A, from the holder"})
            ),
            doc,
        )
        assert bumped.success
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "entity_version_conflict" and issue.path == "$.batches[0].nodes[0]"
        assert (issue.entity_expected_version, issue.actual_entity_version) == (1, 2)
        assert not Batch.all_objects.filter(entity_id=_batch_id(doc)).exists()
        row = Entity.objects.get(pk=a_id)
        assert row.deleted_at is None and row.version == 2
        assert event_delta(events_before, event_counts()) == {(a_id, "update"): 1}
        assert _one_delta(before, snapshot()) == set()

    def test_a_ref_that_finds_a_row_retired_under_it_fails_its_batch(self) -> None:
        """Ref versus id on one object: the ref's search finds the live row, its replace waits
        on the row lock the holder has, the holder tombstones by id and commits — the replace
        meets a tombstone. No second row is minted: the batch fails as a whole."""
        created = create_node("panel", _panel("contested", "Contested"))
        assert created.success and created.entity_id is not None
        a_id = uuid.UUID(str(created.entity_id))
        before, events_before = snapshot(), event_counts()
        doc = _ref_bundle("contested", "Contested, re-sent")
        deleted, result = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(a_id, locked, go, lambda: delete_node(a_id, reason="operator")), doc
        )
        assert deleted.success
        assert Panel.all_objects.filter(slug="contested").count() == 1, "no second row was minted either way"
        _expect_replace_refused_on_the_tombstone(result, a_id, doc, "Contested, re-sent", events_before, before)


def _fixture_node(name: str) -> uuid.UUID:
    return node(name).pk


def _lost_a_deadlock(*results: Any) -> bool:
    """`timing.lost_a_deadlock`'s shape for import results: exactly one import failed, and its
    error is the database's deadlock report surfaced as `execution_failed`."""
    failed = [r for r in results if not r.success]
    if len(failed) != 1 or len(results) - 1 != len([r for r in results if r.success]):
        return False
    return any(e.code == "execution_failed" and "deadlock detected" in e.message for e in failed[0].errors)


def _both_invariants(*ids: uuid.UUID) -> None:
    """After both writers finish: no live edge onto a tombstone, no tombstone re-written."""
    assert live_edges_onto_tombstones() == []
    assert rewritten_tombstones(list(ids)) == []


@pytest.mark.spec("req-grid-batch-corpus-timing-1")
@pytest.mark.spec("req-grid-batch-corpus-timing-2")
@pytest.mark.spec("req-grid-batch-corpus-timing-3")
class TestSchedules:
    """George's write × delete schedules (Issue# 613 - tap). Each docstring states the acceptable
    serial outcomes; the case pins the one the schedule produces and both invariants."""

    def test_write_write_on_one_id_serialises_to_two_replaces(self) -> None:
        """Serial outcomes: A ← first then second, or second then first; either way version 3, two
        update events, both batches committed, the content of whichever ran last. Under the lock
        the holder runs first, so the row carries the contender's payload."""
        a_id = _fixture_node("A")
        before, events_before = snapshot(), event_counts()
        first_doc = _id_bundle(str(a_id), NODE, {"name": "A, by the holder"})
        second_doc = _id_bundle(str(a_id), NODE, {"name": "A, by the contender"})
        first, second = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(a_id, locked, go, lambda: grift_import(first_doc)), second_doc
        )
        if _lost_a_deadlock(first, second):
            # Issue# 611 - tap's other face: a plain replace takes the typed row before the spine row
            # (its Entity read is unlocked), while a writer that locked the spine row first — an OCC
            # replace, a delete, this holder — takes them in the opposite order. Two writers on one
            # id can therefore deadlock instead of serialising; the loser's batch fails with the
            # database's report. Locking the target row first for every verb (PR# 624 - tap) removes
            # the cycle.
            survivor = first if first.success else second
            assert survivor.imported_batches[0].nodes_imported == 1
            assert Entity.objects.get(pk=a_id).version == 2
            pytest.xfail(
                f"pending {TOMBSTONE_RACE} — verified in-body: two writers on one id deadlocked (lost_a_deadlock)"
            )
        assert first.success and second.success, (first.errors, second.errors)
        assert (first.imported_batches[0].nodes_imported, second.imported_batches[0].nodes_imported) == (1, 1)
        row = Entity.objects.get(pk=a_id)
        assert row.deleted_at is None and row.version == 3 and row.name == "A, by the contender"
        assert event_delta(events_before, event_counts()) == {(a_id, "update"): 2}
        assert (
            _one_delta(before, snapshot(), uuid.UUID(_batch_id(first_doc)), uuid.UUID(_batch_id(second_doc))) == set()
        )
        _both_invariants(a_id)

    def test_write_then_delete_on_one_id_ends_with_the_tombstone(self) -> None:
        """Serial outcome: replace (version 2) then the delete section (version 3, two delete
        events). The tombstone is the last write; nothing lands after it."""
        a_id = _fixture_node("A")
        before, events_before = snapshot(), event_counts()
        write_doc = _id_bundle(str(a_id), NODE, {"name": "A, replaced"})
        delete_doc = _doc_with(deletes=_delete_section(str(a_id)))
        written, deleted = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(a_id, locked, go, lambda: grift_import(write_doc)), delete_doc
        )
        assert written.success and deleted.success, (written.errors, deleted.errors)
        assert deleted.imported_batches[0].nodes_deleted == 1
        row = Entity.objects.get(pk=a_id)
        assert row.deleted_at is not None and row.version == 3 and row.name == "A, replaced"
        assert event_delta(events_before, event_counts()) == {(a_id, "update"): 1, (a_id, "delete"): 2}
        assert (
            _one_delta(before, snapshot(), uuid.UUID(_batch_id(write_doc)), uuid.UUID(_batch_id(delete_doc))) == set()
        )
        _both_invariants(a_id)

    def test_delete_section_then_upsert_of_the_same_id_in_two_batches_refuses_the_upsert(self) -> None:
        """Serial outcome: the delete section tombstones A (version 2, two delete events); the
        upsert then meets a tombstone and its batch fails closed. Today the plain replace decides
        on an unlocked read and lands on the tombstone (Issue# 611 - tap), verified in-body."""
        a_id = _fixture_node("A")
        delete_doc = _doc_with(deletes=_delete_section(str(a_id)))
        upsert_doc = _id_bundle(str(a_id), NODE, {"name": "A, upserted after its delete"})
        before, events_before = snapshot(), event_counts()
        deleted, upserted = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(a_id, locked, go, lambda: grift_import(delete_doc)), upsert_doc
        )
        assert deleted.success and deleted.imported_batches[0].nodes_deleted == 1
        row = Entity.objects.get(pk=a_id)
        if _wrote_onto_the_tombstone(upserted, row, upsert_doc, "A, upserted after its delete"):
            assert rewritten_tombstones([a_id]), "the second invariant sees the re-written tombstone"
            pytest.xfail(f"pending {TOMBSTONE_RACE} — verified in-body: the upsert landed on the tombstone (version 3)")
        assert not upserted.success and [(e.code, e.path) for e in upserted.errors] == [
            ("execution_failed", "$.batches[0].nodes[0]")
        ]
        assert not Batch.all_objects.filter(entity_id=_batch_id(upsert_doc)).exists()
        assert row.deleted_at is not None and row.version == 2 and row.name == "A"
        assert event_delta(events_before, event_counts()) == {(a_id, "delete"): 2}
        assert _one_delta(before, snapshot(), uuid.UUID(_batch_id(delete_doc))) == set()
        _both_invariants(a_id)

    def test_delete_delete_on_one_id_tombstones_once(self) -> None:
        """Serial outcomes: the second delete section finds a tombstone and follows its policy —
        `ignore` skips it silently. Under the race the contender planned its delete against a
        live row and the verb it reaches is idempotent on a tombstone (tombstone-6): either way A
        is bumped exactly once, both batches commit, and no write follows the tombstone. The one
        thing the schedule leaves open, recorded here: the contender's bundle-reason event may or
        may not be recorded on the row (two or three delete events)."""
        a_id = _fixture_node("A")
        before, events_before = snapshot(), event_counts()
        first_doc = _doc_with(deletes=_delete_section(str(a_id)))
        second_doc = _doc_with(deletes=_delete_section(str(a_id)))
        first, second = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(a_id, locked, go, lambda: grift_import(first_doc)), second_doc
        )
        assert first.success and second.success, (first.errors, second.errors)
        row = Entity.objects.get(pk=a_id)
        assert row.deleted_at is not None and row.version == 2, "tombstoned exactly once"
        delta = event_delta(events_before, event_counts())
        assert set(delta) == {(a_id, "delete")} and delta[(a_id, "delete")] in (2, 3), delta
        assert (
            _one_delta(before, snapshot(), uuid.UUID(_batch_id(first_doc)), uuid.UUID(_batch_id(second_doc))) == set()
        )
        _both_invariants(a_id)

    def test_edge_created_while_its_endpoint_is_deleted_is_refused(self) -> None:
        """Delete first: the holder tombstones A under its lock; the contender's batch creates an
        edge X→A. Serial outcome (ruled, Issue# 609 - tap): the edge is refused — dangling at
        preflight if the tombstone is already committed, `execution_failed` on the locked
        endpoint if it was live when preflight looked. Today edge creation takes no endpoint lock:
        the contender never blocks and commits a live edge onto the tombstone — the invariant's
        exact violation, verified in-body."""
        a_id, x_id = _fixture_node("A"), _fixture_node("X")
        edge_id = str(uuid.uuid7())
        before, events_before = snapshot(), event_counts()
        doc = _doc_with(edges=(_edge(edge_id, str(x_id), str(a_id)),))
        holder, contender = contend(
            a_id, lambda: delete_node(a_id, reason="operator"), lambda: grift_import(doc), must_block=False
        )
        assert holder.value.success
        result = contender.value
        onto = live_edges_onto_tombstones()
        if result.success and onto == [uuid.UUID(edge_id)]:
            Edge.all_objects.filter(entity_id=edge_id).delete()  # clear the violation for the module invariant
            pytest.xfail(
                "pending unified-systems-com/tap#609 — verified in-body: a live edge was committed onto the tombstone"
            )
        assert not result.success and not Edge.all_objects.filter(entity_id=edge_id).exists()
        assert {e.code for e in result.errors} <= {"dangling_edge", "execution_failed"}, result.errors
        assert not Batch.all_objects.filter(entity_id=_batch_id(doc)).exists()
        assert Entity.objects.get(pk=a_id).version == 2
        assert event_delta(events_before, event_counts()) == {(a_id, "delete"): 1}
        assert _one_delta(before, snapshot()) == set()
        _both_invariants(a_id, x_id)

    def test_endpoint_deleted_while_its_edge_is_created_ends_the_new_edge(self) -> None:
        """Edge first: the holder creates the edge X→A under A's lock and commits; the delete of
        A that waited then ends every live incident edge, the new one included. Serial outcome:
        A and the edge both tombstoned at version 2; the edge's link event and its silent end."""
        a_id, x_id = _fixture_node("A"), _fixture_node("X")
        edge_id = str(uuid.uuid7())
        before, events_before = snapshot(), event_counts()
        doc = _doc_with(edges=(_edge(edge_id, str(x_id), str(a_id)),))
        holder, deleter = contend(a_id, lambda: grift_import(doc), lambda: delete_node(a_id, reason="operator"))
        assert holder.value.success and deleter.value.success, (holder.value.errors, deleter.value.errors)
        edge = Entity.objects.get(pk=uuid.UUID(edge_id))
        assert edge.deleted_at is not None and edge.version == 2
        assert Entity.objects.get(pk=a_id).version == 2 and Entity.objects.get(pk=x_id).version == 1
        assert event_delta(events_before, event_counts()) == {(a_id, "delete"): 1, (edge.pk, "link"): 1}
        assert _one_delta(before, snapshot(), edge.pk, uuid.UUID(_batch_id(doc))) == set()
        _both_invariants(a_id, x_id, edge.pk)

    def test_a_cascade_running_while_a_batch_writes_into_its_subtree_refuses_the_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R contains C. The holder holds C and cascades from R (R, C and the edge retire under
        its locks); the contender's batch replaces C by id and waits on C. Serial outcome: the
        replace meets C's tombstone and fails closed; C carries one cascaded delete event and
        version 2. Today the plain replace lands on the tombstone (Issue# 611 - tap)."""
        from tap_grid.registry import get_model_class

        monkeypatch.setattr(get_model_class(NODE), "CONTAINMENT_EDGES", (NESTS,), raising=False)
        r, c = node("R"), node("C")
        e_rc = contains(r, c)
        before, events_before = snapshot(), event_counts()
        doc = _id_bundle(str(c.pk), NODE, {"name": "C, written during the cascade"})
        cascaded, result = _import_blocked_by_holder(
            lambda locked, go: hold_lock_then(
                c.pk, locked, go, lambda: delete_node(r.pk, cascade="contained", reason="scope_withdrawn")
            ),
            doc,
        )
        assert cascaded.success
        row = Entity.objects.get(pk=c.pk)
        if _wrote_onto_the_tombstone(result, row, doc, "C, written during the cascade"):
            assert rewritten_tombstones([c.pk]), "the second invariant sees the re-written tombstone"
            pytest.xfail(f"pending {TOMBSTONE_RACE} — verified in-body: the replace landed on the cascaded tombstone")
        assert not result.success and [(i.code, i.path) for i in result.errors] == [
            ("execution_failed", "$.batches[0].nodes[0]")
        ]
        assert not Batch.all_objects.filter(entity_id=_batch_id(doc)).exists()
        after = snapshot()
        assert after[r.pk] == (False, 2) and after[c.pk] == (False, 2) and after[e_rc] == (False, 2)
        assert event_delta(events_before, event_counts()) == {
            (r.pk, BatchEventType.DELETE): 1,
            (c.pk, BatchEventType.DELETE): 1,
            (e_rc, BatchEventType.UNLINK): 1,
        }
        assert _one_delta(before, after) == set()
        _both_invariants(r.pk, c.pk, e_rc)
