"""Overlapping deletes serialise without deadlock and never double-write (Issue# 590 - tap).

Two writers on the real database, interleaved deterministically: a second connection
holds a row lock on a chosen node inside an open transaction; the delete under test is
observed — by backend pid, through ``pg_blocking_pids`` — to be blocked by that holder;
the holder does its work and commits; the delete resumes. Every case asserts the ruled
outcome in full: both writers succeed, the subtree retires once, every node and edge
carries exactly one event and one version bump. The cases that once deadlocked are run
several times each, because the defect was an interleaving, not a value.

(The same harness shape lives in the cascade confirmation corpus's timing family; once
both land the helpers move into one home.)
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

from tap_grid.exceptions import is_deadlock
from tap_grid.models import BatchEvent, BatchEventType, Entity
from tap_grid.services import create_edge, create_node, delete_edge_by_entity, delete_node

NODE = "grid_fixtures__node"
NESTS = "PG_NESTS__grid_fixtures"
CASCADE = "req-grid-service-delete-cascade"
JOIN_SECONDS = 20.0
RUNS = 3


@dataclass
class Outcome:
    pid: int | None = None
    value: Any = None
    error: BaseException | None = None
    done: threading.Event = field(default_factory=threading.Event)


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, Outcome]:
    ctx = contextvars.copy_context()
    outcome = Outcome()

    def body() -> None:
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                (outcome.pid,) = cur.fetchone()
            outcome.value = ctx.run(fn)
        except BaseException as exc:  # noqa: BLE001  # read back by the test, which fails loudly
            outcome.error = exc
        finally:
            connection.close()
            outcome.done.set()

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, outcome


def wait_until_blocked_by(waiter: Outcome, holder: Outcome, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if waiter.pid is not None and holder.pid is not None:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_blocking_pids(%s)", [waiter.pid])
                (blockers,) = cur.fetchone()
            if holder.pid in (blockers or []):
                return
        if waiter.done.is_set():
            raise AssertionError("the writer finished without ever blocking on the holder")
        time.sleep(0.02)
    raise AssertionError(f"pid {waiter.pid} never blocked on pid {holder.pid} within {timeout}s")


def finish(*outcomes: tuple[threading.Thread, Outcome]) -> None:
    for thread, outcome in outcomes:
        thread.join(JOIN_SECONDS)
        assert not thread.is_alive(), "a writer never finished — a deadlock or an unreleased lock"
        assert outcome.error is None, f"writer raised: {outcome.error!r}"


def snapshot() -> dict[uuid.UUID, tuple[bool, int]]:
    return {row.pk: (row.deleted_at is not None, row.version) for row in Entity.objects.all()}


def event_counts() -> dict[tuple[uuid.UUID, str], int]:
    counts: dict[tuple[uuid.UUID, str], int] = {}
    for entity_id, event_type in BatchEvent.objects.values_list("entity_id", "event_type"):
        counts[(entity_id, event_type)] = counts.get((entity_id, event_type), 0) + 1
    return counts


def delta(before: dict[tuple[uuid.UUID, str], int]) -> dict[tuple[uuid.UUID, str], int]:
    after = event_counts()
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys if after.get(k, 0) != before.get(k, 0)}


def node(name: str) -> Entity:
    result = create_node(NODE, {"name": name})
    assert result.success, result.errors
    assert result.entity_id is not None
    return Entity.objects.get(pk=result.entity_id)


def contains(a: Entity, b: Entity) -> uuid.UUID:
    return uuid.UUID(str(create_edge(a, b, NESTS).entity_id))


def live(entity_id: uuid.UUID) -> bool:
    return Entity.objects.get(pk=entity_id).deleted_at is None


def once(before: dict[uuid.UUID, tuple[bool, int]], *ids: uuid.UUID) -> None:
    """Every id is retired and its version moved exactly once."""
    after = snapshot()
    for eid in ids:
        assert after[eid][0], f"{eid} should be retired"
        assert after[eid][1] == before[eid][1] + 1, f"{eid} version {before[eid][1]} -> {after[eid][1]}: exactly once"


def untouched(before: dict[uuid.UUID, tuple[bool, int]], *ids: uuid.UUID) -> None:
    after = snapshot()
    for eid in ids:
        assert after[eid] == before[eid], f"{eid} must be untouched: {before[eid]} -> {after[eid]}"


def _hold_lock_then(entity_id: uuid.UUID, locked: threading.Event, go: threading.Event, then: Callable[[], Any]) -> Any:
    with transaction.atomic():
        Entity.objects.select_for_update().get(pk=entity_id)
        locked.set()
        assert go.wait(JOIN_SECONDS), "the test never released the lock holder"
        return then()


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
        once(before, r.pk, a.pk, b.pk, e_ra, e_ab)
        assert delta(events_before) == {
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
        locked, go = threading.Event(), threading.Event()
        holder = in_thread(lambda: _hold_lock_then(c.pk, locked, go, lambda: delete_node(c.pk, reason="operator")))
        assert locked.wait(JOIN_SECONDS)
        cascade = in_thread(lambda: delete_node(r.pk, cascade="contained", reason="scope_withdrawn"))
        try:
            wait_until_blocked_by(cascade[1], holder[1])
        finally:
            go.set()
        finish(holder, cascade)
        assert holder[1].value.success and cascade[1].value.success, (holder[1].value.errors, cascade[1].value.errors)
        once(before, r.pk, c.pk, e_rc, e_cd)
        untouched(before, d.pk)
        assert delta(events_before) == {
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
        once(before, r1.pk, r2.pk, d.pk, e1, e2)
        assert delta(events_before) == {
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

        locked, go = threading.Event(), threading.Event()
        holder = in_thread(lambda: _hold_lock_then(c.pk, locked, go, attach))
        assert locked.wait(JOIN_SECONDS)
        cascade = in_thread(lambda: delete_node(r.pk, cascade="contained"))
        try:
            wait_until_blocked_by(cascade[1], holder[1])
        finally:
            go.set()
        finish(holder, cascade)
        assert cascade[1].value.success, cascade[1].value.errors
        assert not live(r.pk) and not live(c.pk) and not live(state["n"]) and not live(e_rc) and not live(state["e_cn"])
        meta = BatchEvent.objects.get(entity_id=state["n"], event_type=BatchEventType.DELETE).metadata
        assert meta["consequence_of"] == str(c.pk) and meta["cascade_root"] == str(r.pk)

    def test_a_child_reparented_away_before_the_lock_is_not_retired(self, containment: None) -> None:
        """R contains C contains D. B holds C; A's cascade discovers {R, C, D} and blocks on C;
        B ends the containing edge C→D (D now belongs to nobody in the closure) and commits;
        A recomputes under its locks: D is no longer reachable and stays live."""
        r, c, d = node("R"), node("C"), node("D")
        e_rc, e_cd = contains(r, c), contains(c, d)
        locked, go = threading.Event(), threading.Event()
        holder = in_thread(
            lambda: _hold_lock_then(c.pk, locked, go, lambda: delete_edge_by_entity(e_cd, reason="operator"))
        )
        assert locked.wait(JOIN_SECONDS)
        cascade = in_thread(lambda: delete_node(r.pk, cascade="contained"))
        try:
            wait_until_blocked_by(cascade[1], holder[1])
        finally:
            go.set()
        finish(holder, cascade)
        assert holder[1].value.success and cascade[1].value.success
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
