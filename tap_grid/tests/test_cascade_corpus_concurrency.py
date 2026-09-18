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

Known defects are recognised by SHAPE, never by "the test failed" (Issue# 587 - tap): a
case whose writers produce the specific outcome Issue# 590 - tap describes — one writer
loses a deadlock and surfaces the database's error — is reported as an expected failure
naming that issue; any other failure, including a fixture error, a worker exception or a
timeout, is a hard failure. The recognised defect is nondeterministic by nature, so a
clean pass is not evidence the tag is stale; the tag comes off when #590 closes.

Postgres only, by construction: row locks and ``pg_blocking_pids`` are how the interleaving
is made deterministic; no sleep decides an outcome.
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
KNOWN_DEFECT = "unified-systems-com/tap#590"


@dataclass
class Outcome:
    """What a thread produced: its backend pid, its return value or the exception it raised."""

    pid: int | None = None
    value: Any = None
    error: BaseException | None = None
    done: threading.Event = field(default_factory=threading.Event)


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, Outcome]:
    """Run ``fn`` on a thread that inherits THIS test's context (caller context, write hatch,
    ambient batch), records its own Postgres backend pid, and closes its connection at the end."""
    ctx = contextvars.copy_context()
    outcome = Outcome()

    def body() -> None:
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                (outcome.pid,) = cur.fetchone()
            outcome.value = ctx.run(fn)
        except BaseException as exc:  # noqa: BLE001  # the test reads it back and fails loudly
            outcome.error = exc
        finally:
            connection.close()
            outcome.done.set()

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, outcome


def wait_until_blocked_by(waiter: Outcome, holder: Outcome, timeout: float = 10.0) -> None:
    """Block until the waiter's backend is waiting on a lock the holder's backend holds."""
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


def lost_a_deadlock(*results: Any) -> bool:
    """The exact shape Issue# 590 - tap describes: one writer succeeded, one did not, and the
    loser's error is the database's deadlock report surfaced through the service result."""
    failed = [r for r in results if not r.success]
    if len(failed) != 1 or len(results) - 1 != len([r for r in results if r.success]):
        return False
    return any("deadlock detected" in (e.message or "") for e in failed[0].errors)


def known_defect_or_fail(*results: Any) -> None:
    """Either every writer succeeded (the ruled outcome — the caller then asserts it in full),
    or the outcome has exactly the known defect's shape and the case is an expected failure
    naming its issue. Anything else falls through to the caller's assertions and fails."""
    if all(r.success for r in results):
        return
    if lost_a_deadlock(*results):
        pytest.xfail(
            f"pending {KNOWN_DEFECT}: one writer lost a deadlock — {[e.code for r in results for e in r.errors]}"
        )


def wrote_twice(
    before: dict[uuid.UUID, tuple[bool, int]],
    after: dict[uuid.UUID, tuple[bool, int]],
    delta: dict[tuple[uuid.UUID, str], int],
    ids: tuple[uuid.UUID, ...],
) -> list[str]:
    """The second shape Issue# 590 - tap describes: no deadlock, both writers succeeded, and a
    retired entity was written twice — its version moved by more than one, or it carries more
    than one event — because the endpoint tombstone is unconditional and its provenance is
    read before the update blocks on the other writer's lock."""
    twice = [f"{eid}: version {before[eid][1]} -> {after[eid][1]}" for eid in ids if after[eid][1] > before[eid][1] + 1]
    twice += [f"{eid}: {etype} x{n}" for (eid, etype), n in delta.items() if eid in ids and n > 1]
    return twice


def known_double_write_or_fail(
    before: dict[uuid.UUID, tuple[bool, int]],
    after: dict[uuid.UUID, tuple[bool, int]],
    delta: dict[tuple[uuid.UUID, str], int],
    ids: tuple[uuid.UUID, ...],
) -> None:
    """The known defect's second shape, recognised precisely; any other mismatch falls through."""
    twice = wrote_twice(before, after, delta, ids)
    if twice:
        pytest.xfail(f"pending {KNOWN_DEFECT}: written twice by overlapping writers — {twice}")


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


def bumped_once(
    before: dict[uuid.UUID, tuple[bool, int]], after: dict[uuid.UUID, tuple[bool, int]], *ids: uuid.UUID
) -> None:
    for eid in ids:
        assert (
            after[eid][1] == before[eid][1] + 1
        ), f"{eid} version {before[eid][1]} -> {after[eid][1]}: must bump exactly once"


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
        known_defect_or_fail(first[1].value, second[1].value)
        assert first[1].value.success and second[1].value.success, (first[1].value.errors, second[1].value.errors)
        after = snapshot()
        assert not live(r.pk) and not live(a.pk) and not live(b.pk)
        delta = event_delta(events_before, event_counts())
        known_double_write_or_fail(before, after, delta, (r.pk, a.pk, b.pk, e_ra, e_ab))
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
        observed blocked on B at C; B plain-deletes C and commits; A resumes. Ruled: A succeeds,
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
        try:
            wait_until_blocked_by(cascade[1], holder[1])
        finally:
            go.set()
        finish(holder, cascade)
        known_defect_or_fail(holder[1].value, cascade[1].value)
        assert holder[1].value.success and cascade[1].value.success
        assert not live(r.pk) and not live(c.pk) and not live(d.pk)
        after = snapshot()
        bumped_once(before, after, r.pk, c.pk, d.pk, e_rc, e_cd)
        assert event_delta(events_before, event_counts()) == {
            (r.pk, BatchEventType.DELETE): 1,
            (c.pk, BatchEventType.DELETE): 1,
            (d.pk, BatchEventType.DELETE): 1,
            (e_rc, BatchEventType.UNLINK): 1,
        }
        assert latest_event(d.pk, BatchEventType.DELETE).metadata["consequence_of"] == str(c.pk)
        assert latest_event(d.pk, BatchEventType.DELETE).metadata["cascade_root"] == str(r.pk)
        assert unlinks_on(e_cd) == 0, "B's plain delete ended C→D with no edge event; A must not end it again"

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
        known_defect_or_fail(first[1].value, second[1].value)
        assert first[1].value.success and second[1].value.success
        assert not live(r1.pk) and not live(r2.pk) and not live(d.pk)
        after = snapshot()
        delta = event_delta(events_before, event_counts())
        known_double_write_or_fail(before, after, delta, (r1.pk, r2.pk, d.pk, e1, e2))
        bumped_once(before, after, r1.pk, r2.pk, d.pk, e1, e2)
        assert delta == {
            (r1.pk, BatchEventType.DELETE): 1,
            (r2.pk, BatchEventType.DELETE): 1,
            (d.pk, BatchEventType.DELETE): 1,
            (e1, BatchEventType.UNLINK): 1,
            (e2, BatchEventType.UNLINK): 1,
        }

    @pytest.mark.spec(f"{CASCADE}-7")
    def test_a_child_attached_after_discovery_is_not_reached(self, containment: None) -> None:
        """R contains C. Writer B holds C's lock; A cascades from R and is observed blocked on B
        at C; B attaches a NEW child N under C and commits; A resumes. Observed and pinned: N
        was not discovered (discovery precedes the block) so N stays live — but the edge C→N
        IS ended, because the walk gathers a node's incident edges after its tombstone update,
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
        try:
            wait_until_blocked_by(cascade[1], holder[1])
        finally:
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
        holder = in_thread(lambda: _hold_lock_then(x.pk, locked, go, lambda: True))
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
