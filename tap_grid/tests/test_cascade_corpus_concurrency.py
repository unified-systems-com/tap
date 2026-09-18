"""The cascade confirmation corpus, timing family (Issue# 578 - tap).

Corner cases the JSON scenarios cannot express because they need two writers at once:
the same node deleted twice concurrently, a child deleted while its parent's cascade is
in flight, two cascades meeting at a shared child, a child attached after discovery.
Each case is a real interleaving on the real database, not a mock: a second connection
holds a row lock on a chosen node inside an open transaction, the cascade blocks at that
node's tombstone UPDATE, the other writer does its work and commits, and the cascade
resumes. The three corpus assertions still apply — exactly what should retire retired,
nothing else moved, and the records say what they should — and where today's behaviour
is a known defect the case is a strict xfail pending the issue that fixes it, so it fails
the day the fix lands and the tag is removed. History so far: three cases waited on
Issue# 575 - tap (a concurrent repeat delete rewrote history); when PR# 579 - tap landed,
the same three cases showed the fix's per-target row lock deadlocking overlapping writers
instead — Issue# 590 - tap — so they wait on that now. The corpus found it within minutes
of the merge, which is what it is for.

Postgres only, by construction: row locks and `pg_stat_activity` are how the interleaving
is made deterministic (no sleeps decide an outcome).
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from django.db import connection, transaction

from tap_grid.cascade_corpus.runner import event_counts, event_delta, latest_event, snapshot
from tap_grid.models import BatchEvent, BatchEventType, Entity
from tap_grid.services import create_edge, create_node, delete_node

NODE = "grid_fixtures__node"
NESTS = "PG_NESTS__grid_fixtures"
CASCADE = "req-grid-service-delete-cascade"
JOIN_SECONDS = 20.0


@dataclass
class Outcome:
    """What a thread produced: its return value or the exception it raised."""

    value: Any = None
    error: BaseException | None = None
    done: threading.Event = field(default_factory=threading.Event)


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, Outcome]:
    """Run ``fn`` on a thread that inherits THIS test's context (caller context, write hatch,
    ambient batch) and closes its own database connection when it is done."""
    ctx = contextvars.copy_context()
    outcome = Outcome()

    def body() -> None:
        try:
            outcome.value = ctx.run(fn)
        except BaseException as exc:  # noqa: BLE001  # the test reads it back and fails loudly
            outcome.error = exc
        finally:
            connection.close()
            outcome.done.set()

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, outcome


def wait_for_a_blocked_writer(timeout: float = 10.0) -> None:
    """Block until some other connection on this database is waiting on a row lock."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
            (waiting,) = cur.fetchone()
        if waiting:
            return
        time.sleep(0.02)
    raise AssertionError("no writer blocked on a row lock within the timeout")


def finish(*outcomes: tuple[threading.Thread, Outcome]) -> None:
    for thread, outcome in outcomes:
        thread.join(JOIN_SECONDS)
        assert not thread.is_alive(), "a writer never finished — a deadlock or an unreleased lock"
        assert outcome.error is None, f"writer raised: {outcome.error!r}"


def node(name: str) -> Entity:
    result = create_node(NODE, {"name": name})
    assert result.success, result.errors
    assert result.entity_id is not None
    return Entity.objects.get(pk=result.entity_id)


def contains(a: Entity, b: Entity) -> uuid.UUID:
    return uuid.UUID(str(create_edge(a, b, NESTS).entity_id))


def live(entity_id: uuid.UUID) -> bool:
    return Entity.objects.get(pk=entity_id).deleted_at is None


def deletes_on(entity_id: uuid.UUID) -> int:
    return BatchEvent.objects.filter(entity_id=entity_id, event_type=BatchEventType.DELETE).count()


def unlinks_on(entity_id: uuid.UUID) -> int:
    return BatchEvent.objects.filter(entity_id=entity_id, event_type=BatchEventType.UNLINK).count()


@pytest.fixture
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_grid.registry import get_model_class

    monkeypatch.setattr(get_model_class(NODE), "CONTAINMENT_EDGES", (NESTS,), raising=False)


def _hold_lock_then(entity_id: uuid.UUID, locked: threading.Event, go: threading.Event, then: Callable[[], Any]) -> Any:
    """In one transaction: lock the row, say so, wait for the signal, run ``then``, commit."""
    with transaction.atomic():
        Entity.objects.select_for_update().get(pk=entity_id)
        locked.set()
        assert go.wait(JOIN_SECONDS), "the test never released the lock holder"
        return then()


@pytest.mark.cascade_corpus
@pytest.mark.django_db(transaction=True)
@pytest.mark.spec("req-grid-cascade-corpus-timing-1")
@pytest.mark.spec("req-grid-cascade-corpus-timing-2")
class TestTiming:
    @pytest.mark.spec("req-grid-service-delete-tombstone-1")
    @pytest.mark.spec(f"{CASCADE}-3")
    @pytest.mark.xfail(
        strict=True,
        reason="pending unified-systems-com/tap#590: overlapping concurrent deletes deadlock; the loser gets an untyped error",
    )
    def test_two_concurrent_cascades_of_the_same_root_retire_it_once(self, containment: None) -> None:
        """Two writers delete the same root at the same instant. Ruled: both succeed, the
        subtree retires once, every node and edge carries exactly one event."""
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
        for eid in (r.pk, a.pk, b.pk, e_ra, e_ab):
            assert after[eid][1] == before[eid][1] + 1, f"{eid} version must bump exactly once"
        delta = event_delta(events_before, event_counts())
        assert delta == {
            (r.pk, BatchEventType.DELETE): 1,
            (a.pk, BatchEventType.DELETE): 1,
            (b.pk, BatchEventType.DELETE): 1,
            (e_ra, BatchEventType.UNLINK): 1,
            (e_ab, BatchEventType.UNLINK): 1,
        }

    @pytest.mark.spec(f"{CASCADE}-3")
    @pytest.mark.spec(f"{CASCADE}-14")
    @pytest.mark.xfail(
        strict=True, reason="pending unified-systems-com/tap#590: a child deleted mid-cascade deadlocks with the walk"
    )
    def test_a_child_deleted_while_its_parents_cascade_is_in_flight(self, containment: None) -> None:
        """R contains C contains D. Writer B holds C's row lock, writer A cascades from R and
        blocks at C's tombstone; B plain-deletes C and commits; A resumes. Ruled: A succeeds,
        R, C and D are retired, C carries ONE delete event (B's), D is a consequence of C in
        A's cascade, and the edge C→D that B's plain delete ended records no second ending."""
        r, c, d = node("R"), node("C"), node("D")
        e_rc, e_cd = contains(r, c), contains(c, d)
        before = snapshot()
        events_before = event_counts()
        locked, go = threading.Event(), threading.Event()
        holder = in_thread(lambda: _hold_lock_then(c.pk, locked, go, lambda: delete_node(c.pk, reason="operator")))
        assert locked.wait(JOIN_SECONDS)
        cascade = in_thread(lambda: delete_node(r.pk, cascade="contained", reason="scope_withdrawn"))
        wait_for_a_blocked_writer()
        go.set()
        finish(holder, cascade)
        assert holder[1].value.success and cascade[1].value.success
        assert not live(r.pk) and not live(c.pk) and not live(d.pk)
        after = snapshot()
        for eid in (r.pk, c.pk, d.pk, e_rc, e_cd):
            assert after[eid][1] == before[eid][1] + 1, f"{eid} version must bump exactly once"
        delta = event_delta(events_before, event_counts())
        assert delta == {
            (r.pk, BatchEventType.DELETE): 1,
            (c.pk, BatchEventType.DELETE): 1,
            (d.pk, BatchEventType.DELETE): 1,
            (e_rc, BatchEventType.UNLINK): 1,
        }, delta
        assert latest_event(d.pk, BatchEventType.DELETE).metadata["consequence_of"] == str(c.pk)
        assert latest_event(d.pk, BatchEventType.DELETE).metadata["cascade_root"] == str(r.pk)
        assert unlinks_on(e_cd) == 0, "B's plain delete ended C→D with no edge event; A must not end it again"

    @pytest.mark.spec(f"{CASCADE}-13")
    @pytest.mark.spec(f"{CASCADE}-3")
    @pytest.mark.xfail(
        strict=True, reason="pending unified-systems-com/tap#590: two cascades meeting at a shared child deadlock"
    )
    def test_two_cascades_meeting_at_a_shared_child_retire_it_once(self, containment: None) -> None:
        """R1 and R2 both contain D; both cascades start together. Ruled: both succeed, D is
        retired once with one event, each root's own edge into D ends once."""
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
        for eid in (r1.pk, r2.pk, d.pk, e1, e2):
            assert after[eid][1] == before[eid][1] + 1, f"{eid} version must bump exactly once"
        delta = event_delta(events_before, event_counts())
        assert delta == {
            (r1.pk, BatchEventType.DELETE): 1,
            (r2.pk, BatchEventType.DELETE): 1,
            (d.pk, BatchEventType.DELETE): 1,
            (e1, BatchEventType.UNLINK): 1,
            (e2, BatchEventType.UNLINK): 1,
        }, delta

    @pytest.mark.spec(f"{CASCADE}-7")
    def test_a_child_attached_after_discovery_is_not_reached(self, containment: None) -> None:
        """R contains C. Writer B holds C's lock; A cascades from R and blocks at C; B attaches
        a NEW child N under C and commits; A resumes. Observed and pinned: N was not
        discovered (discovery precedes the block) so N stays live — but the edge C→N IS
        ended, because the walk gathers a node's incident edges after its tombstone update,
        i.e. after B committed. No dangling edge survives; the late node is simply not
        cascaded. Whether a late child should be retired is the reparenting race, Backlog
        as cascade-7; this case flips when that is built."""
        r, c = node("R"), node("C")
        e_rc = contains(r, c)
        before = snapshot()
        holder_state: dict[str, Any] = {}

        def attach() -> Any:
            n = node("N")
            holder_state["n"] = n.pk
            holder_state["e_cn"] = contains(c, n)
            return True

        locked, go = threading.Event(), threading.Event()
        holder = in_thread(lambda: _hold_lock_then(c.pk, locked, go, attach))
        assert locked.wait(JOIN_SECONDS)
        cascade = in_thread(lambda: delete_node(r.pk, cascade="contained"))
        wait_for_a_blocked_writer()
        go.set()
        finish(holder, cascade)
        assert cascade[1].value.success, cascade[1].value.errors
        assert not live(r.pk) and not live(c.pk)
        assert live(holder_state["n"]), "N was attached after discovery; the walk never saw it"
        assert not live(e_rc)
        assert not live(holder_state["e_cn"]), "the late edge is gathered after C's tombstone, so it ends with C"
        assert unlinks_on(holder_state["e_cn"]) == 1
        assert latest_event(holder_state["e_cn"], BatchEventType.UNLINK).metadata["consequence_of"] == str(c.pk)
        assert deletes_on(holder_state["n"]) == 0, "N was never discovered and records nothing"
        assert deletes_on(c.pk) == 1
        after = snapshot()
        for eid in (r.pk, c.pk, e_rc):
            assert after[eid][1] == before[eid][1] + 1, f"{eid} version must bump exactly once"
