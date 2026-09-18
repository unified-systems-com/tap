"""The cascade confirmation corpus, timing family (Issue# 578 - tap).

Corner cases the JSON scenarios cannot express because they need two writers at once:
the same node deleted twice concurrently, a child deleted while its parent's cascade is
in flight, two cascades meeting at a shared child, a child attached after discovery.
Each case is a real interleaving on the real database, not a mock: a second connection
holds a row lock on a chosen node inside an open transaction; the cascade is observed —
by backend pid, through ``pg_blocking_pids`` — to be blocked by exactly that holder; the
holder does its work and commits; the cascade resumes. The three corpus assertions still
apply: exactly what should retire retired, nothing else moved, the records say what they
should.

Known defects are recognised by SHAPE, never by "the test failed" (Issue# 587 - tap): the
recognisers below (`lost_a_deadlock`, `wrote_twice`) name the two shapes Issue# 590 - tap
had, and stay as the pattern for the next known defect; any failure that is not a named
shape — a fixture error, a worker exception, a timeout — is a hard failure. #590 is fixed
(PR# 592 - tap: one global lock order, the closure recomputed under locks) and no case
carries a pending shape today.

Postgres only, by construction: row locks and ``pg_blocking_pids`` are how the interleaving
is made deterministic; no sleep decides an outcome.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from tap_grid.cascade_corpus.timing import (
    JOIN_SECONDS,
    NESTS,
    NODE,
    Outcome,
    bumped_once,
    contains,
    contend,
    deletes_on,
    event_counts,
    event_delta,
    finish,
    hold_lock_then,
    in_thread,
    latest_event,
    live,
    lost_a_deadlock,
    node,
    snapshot,
    unlinks_on,
    wait_until_blocked_by,
    wrote_twice,
)
from tap_grid.models import BatchEventType, Entity
from tap_grid.services import delete_node

CASCADE = "req-grid-service-delete-cascade"
KNOWN_DEFECT = "unified-systems-com/tap#590"


@pytest.fixture
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_grid.registry import get_model_class

    monkeypatch.setattr(get_model_class(NODE), "CONTAINMENT_EDGES", (NESTS,), raising=False)


@pytest.mark.cascade_corpus
@pytest.mark.django_db(transaction=True)
@pytest.mark.spec("req-grid-cascade-corpus-timing-1")
@pytest.mark.spec("req-grid-cascade-corpus-timing-2")
class TestTiming:
    @pytest.mark.spec("req-grid-service-delete-tombstone-1")
    @pytest.mark.spec(f"{CASCADE}-3")
    def test_two_concurrent_cascades_of_the_same_root_retire_it_once(self, containment: None) -> None:
        """Two writers delete the same root at the same instant. Ruled: both succeed, the
        subtree retires once, every node and edge carries exactly one event and one bump."""
        r, a, b = node("R"), node("A"), node("B")
        e_ra, e_ab = contains(r, a), contains(a, b)
        before = snapshot()
        events_before = event_counts()
        barrier = threading.Barrier(2, timeout=JOIN_SECONDS)

        def writer() -> Any:
            barrier.wait()
            return delete_node(r.pk, cascade="contained", reason="scope_withdrawn")

        first, second = in_thread(writer), in_thread(writer)
        finish(first, second)
        assert first[1].value.success and second[1].value.success, (first[1].value.errors, second[1].value.errors)
        after = snapshot()
        assert not live(r.pk) and not live(a.pk) and not live(b.pk)
        delta = event_delta(events_before, event_counts())
        bumped_once(before, after, r.pk, a.pk, b.pk, e_ra, e_ab)
        assert delta == {
            (r.pk, BatchEventType.DELETE): 1,
            (a.pk, BatchEventType.DELETE): 1,
            (b.pk, BatchEventType.DELETE): 1,
            (e_ra, BatchEventType.UNLINK): 1,
            (e_ab, BatchEventType.UNLINK): 1,
        }

    @pytest.mark.spec(f"{CASCADE}-3")
    @pytest.mark.spec(f"{CASCADE}-14")
    def test_a_child_deleted_while_its_parents_cascade_is_in_flight(self, containment: None) -> None:
        """R contains C contains D. Writer B holds C's row lock; writer A cascades from R and is
        observed blocked on B at C; B plain-deletes C (no cascade) and commits; A resumes and
        recomputes its closure under its locks. C is already retired and its edges ended, so
        D is no longer reachable from R: B chose a plain delete and A does not turn it into a
        cascade. Both succeed; R and C retire once each; C's one event is B's; D is untouched;
        the edges B ended are not ended again (PR# 592 - tap, cascade-7)."""
        r, c, d = node("R"), node("C"), node("D")
        e_rc, e_cd = contains(r, c), contains(c, d)
        before = snapshot()
        events_before = event_counts()
        holder, cascade = contend(
            c.pk,
            lambda: delete_node(c.pk, reason="operator"),
            lambda: delete_node(r.pk, cascade="contained", reason="scope_withdrawn"),
        )
        assert holder.value.success and cascade.value.success, (holder.value.errors, cascade.value.errors)
        assert not live(r.pk) and not live(c.pk)
        assert live(d.pk), "D's containing path was gone before A held its locks"
        after = snapshot()
        bumped_once(before, after, r.pk, c.pk, e_rc, e_cd)
        assert after[d.pk] == before[d.pk], "D is untouched"
        assert event_delta(events_before, event_counts()) == {
            (r.pk, BatchEventType.DELETE): 1,
            (c.pk, BatchEventType.DELETE): 1,
        }, "C's event is B's; B's plain delete records no edge events and A adds none"
        assert latest_event(c.pk, BatchEventType.DELETE).metadata["reason"] == "operator"

    @pytest.mark.spec(f"{CASCADE}-13")
    @pytest.mark.spec(f"{CASCADE}-3")
    def test_two_cascades_meeting_at_a_shared_child_retire_it_once(self, containment: None) -> None:
        """R1 and R2 both contain D; both cascades start together. Ruled: both succeed, D is
        retired once with one event, each root's own edge into D ends once. A start barrier
        cannot force the overlap, so a clean pass proves only that this run did not overlap."""
        r1, r2, d = node("R1"), node("R2"), node("D")
        e1, e2 = contains(r1, d), contains(r2, d)
        before = snapshot()
        events_before = event_counts()
        barrier = threading.Barrier(2, timeout=JOIN_SECONDS)

        def writer(root: Entity) -> Callable[[], Any]:
            def run() -> Any:
                barrier.wait()
                return delete_node(root.pk, cascade="contained")

            return run

        first, second = in_thread(writer(r1)), in_thread(writer(r2))
        finish(first, second)
        assert first[1].value.success and second[1].value.success
        assert not live(r1.pk) and not live(r2.pk) and not live(d.pk)
        after = snapshot()
        delta = event_delta(events_before, event_counts())
        bumped_once(before, after, r1.pk, r2.pk, d.pk, e1, e2)
        assert delta == {
            (r1.pk, BatchEventType.DELETE): 1,
            (r2.pk, BatchEventType.DELETE): 1,
            (d.pk, BatchEventType.DELETE): 1,
            (e1, BatchEventType.UNLINK): 1,
            (e2, BatchEventType.UNLINK): 1,
        }

    @pytest.mark.spec(f"{CASCADE}-7")
    def test_a_child_attached_before_the_lock_is_retired(self, containment: None) -> None:
        """R contains C. Writer B holds C's lock; A cascades from R, discovers {R, C} and is
        observed blocked on B at C; B attaches a NEW child N under C and commits; A resumes,
        recomputes its closure under its locks, and retires N too — with its event naming C
        as the node it was a consequence of and R as the root (cascade-7, PR# 592 - tap)."""
        r, c = node("R"), node("C")
        e_rc = contains(r, c)
        before = snapshot()
        holder_state: dict[str, Any] = {}

        def attach() -> Any:
            n = node("N")
            holder_state["n"] = n.pk
            holder_state["e_cn"] = contains(c, n)
            return True

        _, cascade = contend(c.pk, attach, lambda: delete_node(r.pk, cascade="contained"))
        assert cascade.value.success, cascade.value.errors
        assert not live(r.pk) and not live(c.pk) and not live(holder_state["n"])
        assert not live(e_rc) and not live(holder_state["e_cn"])
        assert deletes_on(holder_state["n"]) == 1 and unlinks_on(holder_state["e_cn"]) == 1
        meta = latest_event(holder_state["n"], BatchEventType.DELETE).metadata
        assert meta["consequence_of"] == str(c.pk) and meta["cascade_root"] == str(r.pk)
        assert deletes_on(c.pk) == 1
        after = snapshot()
        bumped_once(before, after, r.pk, c.pk, e_rc)


@pytest.mark.cascade_corpus
@pytest.mark.django_db(transaction=True)
@pytest.mark.spec("req-grid-cascade-corpus-timing-1")
class TestTheHarnessItself:
    """Negative controls (Issue# 587 - tap): the known-defect recogniser accepts only the
    defect's exact shape, and nothing else a writer can do is swallowed."""

    def test_a_worker_exception_is_a_hard_failure(self) -> None:
        thread, outcome = in_thread(lambda: 1 / 0)
        with pytest.raises(AssertionError, match="writer raised"):
            finish((thread, outcome))
        assert isinstance(outcome.error, ZeroDivisionError)
        assert outcome.pid is not None, "the pid is recorded before the body runs"

    def test_the_recogniser_rejects_an_unrelated_failure(self) -> None:
        from tap_grid.service_types import ServiceError, WriteResult

        ok = WriteResult(success=True, batch_id="b", operation="delete_node")
        other = WriteResult(
            success=False,
            batch_id="b",
            operation="delete_node",
            errors=[ServiceError(code="not_found", message="gone")],
        )
        both_fail = WriteResult(
            success=False,
            batch_id="b",
            operation="delete_node",
            errors=[ServiceError(code="internal_error", message="deadlock detected")],
        )
        assert not lost_a_deadlock(ok, other), "a non-deadlock loser is not the known defect"
        assert not lost_a_deadlock(both_fail, both_fail), "two losers is not the known defect"
        assert not lost_a_deadlock(ok, ok)
        assert lost_a_deadlock(ok, both_fail)

    def test_the_double_write_recogniser_needs_a_real_double_write(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        before = {a: (False, 1), b: (False, 1)}
        once = {a: (True, 2), b: (True, 2)}
        assert wrote_twice(before, once, {(a, "delete"): 1, (b, "unlink"): 1}, (a, b)) == []
        assert wrote_twice(before, {a: (True, 3), b: (True, 2)}, {(a, "delete"): 1}, (a, b)) == [f"{a}: version 1 -> 3"]
        assert wrote_twice(before, once, {(b, "unlink"): 2}, (a, b)) == [f"{b}: unlink x2"]
        assert wrote_twice(before, once, {(uuid.uuid4(), "delete"): 2}, (a, b)) == [], "an outsider is not this shape"

    def test_a_blocked_writer_is_identified_by_pid(self) -> None:
        """The wait names the holder: a writer blocked by someone ELSE does not satisfy it."""
        x = node("X")
        locked, go = threading.Event(), threading.Event()
        holder = in_thread(lambda: hold_lock_then(x.pk, locked, go, lambda: True))
        assert locked.wait(JOIN_SECONDS)
        writer = in_thread(lambda: delete_node(x.pk))
        try:
            wait_until_blocked_by(writer[1], holder[1])
            with pytest.raises(AssertionError, match="never blocked"):
                wait_until_blocked_by(writer[1], Outcome(pid=-1), timeout=0.3)
        finally:
            go.set()
        finish(holder, writer)
        assert writer[1].value.success
