"""Overlapping deletes serialise without deadlock and never double-write (Issue# 590 - tap).

Two writers on the real database, interleaved deterministically: a second connection
holds a row lock on a chosen node inside an open transaction; the delete under test is
observed — by backend pid, through ``pg_blocking_pids`` — to be blocked by that holder;
the holder does its work and commits; the delete resumes. Every case asserts the ruled
outcome in full: both writers succeed, the subtree retires once, every node and edge
carries exactly one event and one version bump. The cases that once deadlocked are run
several times each, because the defect was an interleaving, not a value.

The harness is `tap_grid.cascade_corpus.timing`, shared with the corpus's timing family.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from tap_grid.cascade_corpus.timing import (
    JOIN_SECONDS,
    NESTS,
    NODE,
    bumped_once,
    contains,
    contend,
    event_counts,
    event_delta,
    finish,
    in_thread,
    live,
    node,
    snapshot,
    untouched,
)
from tap_grid.exceptions import is_deadlock
from tap_grid.models import BatchEvent, BatchEventType, Entity
from tap_grid.services import delete_edge_by_entity, delete_node

CASCADE = "req-grid-service-delete-cascade"
RUNS = 3


@pytest.fixture
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_grid.registry import get_model_class

    monkeypatch.setattr(get_model_class(NODE), "CONTAINMENT_EDGES", (NESTS,), raising=False)


@pytest.mark.django_db(transaction=True)
@pytest.mark.spec(f"{CASCADE}-19")
class TestOverlappingWriters:
    @pytest.mark.parametrize("run", range(RUNS))
    @pytest.mark.spec("req-grid-service-delete-tombstone-6")
    def test_two_concurrent_cascades_of_the_same_root_retire_it_once(self, containment: None, run: int) -> None:
        r, a, b = node("R"), node("A"), node("B")
        e_ra, e_ab = contains(r, a), contains(a, b)
        before, events_before = snapshot(), event_counts()
        barrier = threading.Barrier(2, timeout=JOIN_SECONDS)

        def writer() -> Any:
            barrier.wait()
            return delete_node(r.pk, cascade="contained", reason="scope_withdrawn")

        first, second = in_thread(writer), in_thread(writer)
        finish(first, second)
        assert first[1].value.success and second[1].value.success, (first[1].value.errors, second[1].value.errors)
        bumped_once(before, snapshot(), r.pk, a.pk, b.pk, e_ra, e_ab)
        assert event_delta(events_before, event_counts()) == {
            (r.pk, BatchEventType.DELETE): 1,
            (a.pk, BatchEventType.DELETE): 1,
            (b.pk, BatchEventType.DELETE): 1,
            (e_ra, BatchEventType.UNLINK): 1,
            (e_ab, BatchEventType.UNLINK): 1,
        }

    @pytest.mark.parametrize("run", range(RUNS))
    @pytest.mark.spec(f"{CASCADE}-3")
    def test_a_child_deleted_while_its_parents_cascade_is_in_flight(self, containment: None, run: int) -> None:
        """B holds C; A's cascade from R is blocked on B at C; B plain-deletes C (no cascade)
        and commits; A resumes and recomputes its closure under its locks. C is already
        retired and its edges ended, so D is no longer reachable from R: B chose a plain
        delete, and A does not turn it into a cascade. Both succeed; R and C retire once
        each; C's one event is B's; D is untouched; the edges B ended are not ended again."""
        r, c, d = node("R"), node("C"), node("D")
        e_rc, e_cd = contains(r, c), contains(c, d)
        before, events_before = snapshot(), event_counts()
        holder, cascade = contend(
            c.pk,
            lambda: delete_node(c.pk, reason="operator"),
            lambda: delete_node(r.pk, cascade="contained", reason="scope_withdrawn"),
        )
        assert holder.value.success and cascade.value.success, (holder.value.errors, cascade.value.errors)
        bumped_once(before, snapshot(), r.pk, c.pk, e_rc, e_cd)
        untouched(before, snapshot(), d.pk)
        assert event_delta(events_before, event_counts()) == {
            (r.pk, BatchEventType.DELETE): 1,
            (c.pk, BatchEventType.DELETE): 1,
        }, "C's event is B's plain delete; B's plain delete records no edge events and A must not add any"
        assert BatchEvent.objects.get(entity_id=c.pk, event_type=BatchEventType.DELETE).metadata["reason"] == "operator"

    @pytest.mark.parametrize("run", range(RUNS))
    @pytest.mark.spec(f"{CASCADE}-13")
    def test_two_cascades_meeting_at_a_shared_child_retire_it_once(self, containment: None, run: int) -> None:
        r1, r2, d = node("R1"), node("R2"), node("D")
        e1, e2 = contains(r1, d), contains(r2, d)
        before, events_before = snapshot(), event_counts()
        barrier = threading.Barrier(2, timeout=JOIN_SECONDS)

        def writer(root: Entity) -> Callable[[], Any]:
            def run_it() -> Any:
                barrier.wait()
                return delete_node(root.pk, cascade="contained")

            return run_it

        first, second = in_thread(writer(r1)), in_thread(writer(r2))
        finish(first, second)
        assert first[1].value.success and second[1].value.success, (first[1].value.errors, second[1].value.errors)
        bumped_once(before, snapshot(), r1.pk, r2.pk, d.pk, e1, e2)
        assert event_delta(events_before, event_counts()) == {
            (r1.pk, BatchEventType.DELETE): 1,
            (r2.pk, BatchEventType.DELETE): 1,
            (d.pk, BatchEventType.DELETE): 1,
            (e1, BatchEventType.UNLINK): 1,
            (e2, BatchEventType.UNLINK): 1,
        }


@pytest.mark.django_db(transaction=True)
@pytest.mark.spec(f"{CASCADE}-6")
@pytest.mark.spec(f"{CASCADE}-7")
class TestClosureUnderLocks:
    def test_a_child_attached_before_the_lock_is_retired(self, containment: None) -> None:
        """R contains C. B holds C; A's cascade discovers {R, C} and blocks on C; B attaches N
        under C and commits; A recomputes the closure under its locks and retires N too."""
        r, c = node("R"), node("C")
        e_rc = contains(r, c)
        state: dict[str, Any] = {}

        def attach() -> Any:
            n = node("N")
            state["n"], state["e_cn"] = n.pk, contains(c, n)
            return True

        _, cascade = contend(c.pk, attach, lambda: delete_node(r.pk, cascade="contained"))
        assert cascade.value.success, cascade.value.errors
        assert not live(r.pk) and not live(c.pk) and not live(state["n"]) and not live(e_rc) and not live(state["e_cn"])
        meta = BatchEvent.objects.get(entity_id=state["n"], event_type=BatchEventType.DELETE).metadata
        assert meta["consequence_of"] == str(c.pk) and meta["cascade_root"] == str(r.pk)

    def test_a_child_reparented_away_before_the_lock_is_not_retired(self, containment: None) -> None:
        """R contains C contains D. B holds C; A's cascade discovers {R, C, D} and blocks on C;
        B ends the containing edge C→D (D now belongs to nobody in the closure) and commits;
        A recomputes under its locks: D is no longer reachable and stays live."""
        r, c, d = node("R"), node("C"), node("D")
        e_rc, e_cd = contains(r, c), contains(c, d)
        holder, cascade = contend(
            c.pk, lambda: delete_edge_by_entity(e_cd, reason="operator"), lambda: delete_node(r.pk, cascade="contained")
        )
        assert holder.value.success and cascade.value.success
        assert not live(r.pk) and not live(c.pk) and not live(e_rc)
        assert live(d.pk), "D's containing edge was gone before the cascade held its locks"
        assert not BatchEvent.objects.filter(entity_id=d.pk, event_type=BatchEventType.DELETE).exists()


@pytest.mark.spec(f"{CASCADE}-19")
def test_write_conflict_is_typed() -> None:
    """A deadlock anywhere in the cause chain is recognised; anything else is not."""
    import psycopg.errors
    from django.db import OperationalError

    inner = psycopg.errors.DeadlockDetected("deadlock detected")
    wrapped = OperationalError("deadlock detected")
    wrapped.__cause__ = inner
    assert is_deadlock(wrapped)
    assert is_deadlock(inner)
    assert not is_deadlock(OperationalError("could not connect"))
    other = OperationalError("x")
    other.__cause__ = psycopg.errors.UniqueViolation("dup")
    assert not is_deadlock(other)
    from tap_grid.service_types import ServiceError

    assert ServiceError(code="write_conflict", message="m").code == "write_conflict"
