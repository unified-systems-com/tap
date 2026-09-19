"""The batch playground's timing family (Issue# 603 - tap): two-writer interleavings the JSON
cannot express, made deterministic on the real database with the cascade corpus's harness
(``tap_grid.cascade_corpus.timing``): a holder takes a lock — the identity advisory lock a ref
resolution takes, or a row lock — and the contending import is observed blocked on it by pid
before the holder does its work and commits. Every case asserts the same things a shaped
scenario does: exact rows and versions, nothing else written, event deltas, result shape.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest
from django.db import transaction

from tap_grid.cascade_corpus.timing import (
    JOIN_SECONDS,
    event_counts,
    event_delta,
    finish,
    hold_lock_then,
    in_thread,
    snapshot,
    wait_until_blocked_by,
)
from tap_grid.grift import grift_import
from tap_grid.models import Batch, Entity
from tap_grid.services import create_node, delete_node, replace_node, resolve_identity
from tap_web.models import Panel

pytestmark = [pytest.mark.batch_corpus, pytest.mark.django_db(transaction=True)]

VIEW = "tap_web/panel_error.html"


def _expect_replace_refused_on_the_tombstone(
    result: Any, a_id: uuid.UUID, doc: dict[str, Any], name_from_bundle: str, events_before: Any, before: Any
) -> None:
    """The ruled outcome (Issue# 611 - tap, fixed): the replace read the committed tombstone under
    the row lock and refused; the batch wrote nothing and only the delete bumped the row."""
    row = Entity.objects.get(pk=a_id)
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
    bid = str(uuid.uuid7())
    return {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {"entity_id": bid, "entity_type": "batch", "name": "timing", "dimensions": {}},
                "batch_node": {
                    "name": "timing",
                    "description": "",
                    "description_json": None,
                    "source": "batch_corpus",
                    "metadata": {},
                },
                "nodes": list(nodes),
                "edges": [],
            }
        ],
    }


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
