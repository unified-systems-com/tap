"""Two-writer interleavings on the real database, for the corpus's timing family and the
delete pipeline's own concurrency tests (one home for both — Issue# 590 - tap).

A writer runs on a thread that inherits the test's context (caller context, write hatch,
ambient batch), records its Postgres backend pid, and closes its own connection. A holder
takes ``SELECT … FOR UPDATE`` on a chosen row inside an open transaction and waits for a
signal; a writer blocked on it is observed by pid through ``pg_blocking_pids`` — never
"some backend is waiting", never a sleep. Known defects are recognised by shape
(``lost_a_deadlock``, ``wrote_twice``), never by "the test failed".

Everything here goes through the public service surface; nothing imports the pipeline.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from django.db import connection, transaction

from tap_grid.cascade_corpus.runner import event_counts, event_delta, labelled, latest_event, snapshot
from tap_grid.models import BatchEvent, BatchEventType, Edge, Entity
from tap_grid.services import create_edge, create_node

__all__ = [
    "JOIN_SECONDS",
    "NESTS",
    "NODE",
    "Outcome",
    "bumped_once",
    "contains",
    "contend",
    "deletes_on",
    "event_counts",
    "event_delta",
    "finish",
    "hold_lock_then",
    "in_thread",
    "latest_event",
    "live",
    "live_edges_onto_tombstones",
    "lost_a_deadlock",
    "node",
    "rewritten_tombstones",
    "snapshot",
    "unlinks_on",
    "untouched",
    "wait_until_blocked_by",
    "wrote_twice",
]

NODE = "grid_fixtures__node"
NESTS = "PG_NESTS__grid_fixtures"
JOIN_SECONDS = 20.0


@dataclass
class Outcome:
    """What a thread produced: its backend pid, its return value or the exception it raised."""

    pid: int | None = None
    value: Any = None
    error: BaseException | None = None
    done: threading.Event = field(default_factory=threading.Event)


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, Outcome]:
    """Run ``fn`` on a thread that inherits THIS test's context, records its own Postgres
    backend pid before the body runs, and closes its connection at the end."""
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
    """Join every writer with a timeout; a hang or a raise is a hard failure."""
    for thread, outcome in outcomes:
        thread.join(JOIN_SECONDS)
        _require(not thread.is_alive(), "a writer never finished — a deadlock or an unreleased lock")
        _require(outcome.error is None, f"writer raised: {outcome.error!r}")


def hold_lock_then(entity_id: uuid.UUID, locked: threading.Event, go: threading.Event, then: Callable[[], Any]) -> Any:
    """In one transaction: lock the row, say so, wait for the signal, run ``then``, commit."""
    with transaction.atomic():
        Entity.objects.select_for_update().get(pk=entity_id)
        locked.set()
        _require(go.wait(JOIN_SECONDS), "the test never released the lock holder")
        return then()


def contend(
    lock_on: uuid.UUID,
    holder_does: Callable[[], Any],
    contender: Callable[[], Any],
    *,
    must_block: bool = True,
) -> tuple[Outcome, Outcome]:
    """The one interleaving every timing case is built from: a holder locks ``lock_on`` and,
    once the contender is observed blocked on it, runs ``holder_does`` and commits; the
    contender then proceeds. Both outcomes are returned after both writers have finished.

    ``must_block=False`` is the schedule for a contender whose lock relationship with the
    holder is the thing under test (Issue# 609 - tap: an edge creation that does not yet
    lock its endpoints never blocks on a delete of one): the holder is released once the
    contender is observed blocked OR has finished on its own, and the case judges the
    committed state either way — a known defect is then recognised by shape, never by a
    harness error.
    """
    locked, go = threading.Event(), threading.Event()
    holder = in_thread(lambda: hold_lock_then(lock_on, locked, go, holder_does))
    _require(locked.wait(JOIN_SECONDS), "the holder never took its lock")
    other = in_thread(contender)
    try:
        if must_block:
            wait_until_blocked_by(other[1], holder[1])
        else:
            _wait_until_blocked_or_done(other[1], holder[1])
    finally:
        go.set()
    finish(holder, other)
    return holder[1], other[1]


def _wait_until_blocked_or_done(waiter: Outcome, holder: Outcome, timeout: float = 10.0) -> None:
    try:
        wait_until_blocked_by(waiter, holder, timeout)
    except AssertionError as exc:
        if not waiter.done.is_set():
            raise
        _require("without ever blocking" in str(exc), str(exc))


def live_edges_onto_tombstones() -> list[uuid.UUID]:
    """Live edges with a tombstoned endpoint, as ids — ``Edge.live_onto_tombstones()``'s query
    (the tombstone invariant, empty at every committed state), read here for the timing cases."""
    return list(Edge.live_onto_tombstones().order_by("entity_id").values_list("entity_id", flat=True))


def rewritten_tombstones(ids: tuple[uuid.UUID, ...] | list[uuid.UUID]) -> list[str]:
    """Tombstoned rows among ``ids`` that were written after they were tombstoned: a create,
    update or link event recorded after the tombstone was decided. The second invariant every
    schedule asserts: no tombstone is re-written."""
    out: list[str] = []
    for eid in ids:
        row = Entity.objects.get(pk=eid)
        if row.deleted_at is None:
            continue
        later = BatchEvent.objects.filter(
            entity_id=eid,
            event_type__in=[BatchEventType.UPDATE, BatchEventType.CREATE, BatchEventType.LINK],
            timestamp__gt=_ended_at(row),
        )
        if later.exists():
            out.append(f"{eid}: written after its tombstone ({[e.event_type for e in later]})")
    return out


def _ended_at(row: Entity) -> Any:
    """When the tombstone was decided: the later of ``deleted_at`` (a verb may compute it before
    it waits on a lock) and the FIRST delete/unlink event that recorded it — for an edge ended
    silently by a node delete, the first delete event of either endpoint (the edge ended when its
    first endpoint did; a later delete of the other endpoint must not move the ending forward and
    hide a write in between — Codex, PR# 637 - tap)."""
    ended = row.deleted_at
    if ended is None:
        raise AssertionError(f"{row.pk} is live; only a tombstone has an ending")
    ending = [BatchEventType.DELETE, BatchEventType.UNLINK]
    own = BatchEvent.objects.filter(entity_id=row.pk, event_type__in=ending).order_by("timestamp").first()
    if own is not None:
        return max(ended, own.timestamp)
    edge = cast(Edge | None, Edge.all_objects.filter(entity_id=row.pk).first())
    if edge is None:
        return ended
    endpoint_delete = (
        BatchEvent.objects.filter(
            entity_id__in=[edge.from_entity_id, edge.to_entity_id], event_type=BatchEventType.DELETE
        )
        .order_by("timestamp")
        .first()
    )
    return ended if endpoint_delete is None else max(ended, endpoint_delete.timestamp)


def lost_a_deadlock(*results: Any) -> bool:
    """The first shape Issue# 590 - tap had: one writer succeeded, one did not, and the
    loser's error is the database's deadlock report surfaced through the service result."""
    failed = [r for r in results if not r.success]
    if len(failed) != 1 or len(results) - 1 != len([r for r in results if r.success]):
        return False
    return any("deadlock detected" in (e.message or "") for e in failed[0].errors)


def wrote_twice(
    before: dict[uuid.UUID, tuple[bool, int]],
    after: dict[uuid.UUID, tuple[bool, int]],
    delta: dict[tuple[uuid.UUID, str], int],
    ids: tuple[uuid.UUID, ...],
) -> list[str]:
    """The second shape Issue# 590 - tap had: no deadlock, both writers succeeded, and a
    retired entity was written twice — its version moved by more than one, or it carries
    more than one event."""
    twice = [f"{eid}: version {before[eid][1]} -> {after[eid][1]}" for eid in ids if after[eid][1] > before[eid][1] + 1]
    twice += [f"{eid}: {etype} x{n}" for (eid, etype), n in delta.items() if eid in ids and n > 1]
    return twice


def node(name: str) -> Entity:
    result = create_node(NODE, {"name": name}, caller_context=labelled("timing fixture node"))
    _require(result.success, f"could not create {name}: {result.errors}")
    if result.entity_id is None:
        raise AssertionError(f"no entity id for {name}")
    return Entity.objects.get(pk=result.entity_id)


def contains(a: Entity, b: Entity) -> uuid.UUID:
    return uuid.UUID(str(create_edge(a, b, NESTS, caller_context=labelled("timing fixture edge")).entity_id))


def live(entity_id: uuid.UUID) -> bool:
    return Entity.objects.get(pk=entity_id).deleted_at is None


def deletes_on(entity_id: uuid.UUID) -> int:
    return BatchEvent.objects.filter(entity_id=entity_id, event_type=BatchEventType.DELETE).count()


def unlinks_on(entity_id: uuid.UUID) -> int:
    return BatchEvent.objects.filter(entity_id=entity_id, event_type=BatchEventType.UNLINK).count()


def bumped_once(
    before: dict[uuid.UUID, tuple[bool, int]], after: dict[uuid.UUID, tuple[bool, int]], *ids: uuid.UUID
) -> None:
    """Every id is retired and its version moved exactly once."""
    for eid in ids:
        _require(after[eid][0], f"{eid} should be retired")
        _require(
            after[eid][1] == before[eid][1] + 1, f"{eid} version {before[eid][1]} -> {after[eid][1]}: exactly once"
        )


def untouched(
    before: dict[uuid.UUID, tuple[bool, int]], after: dict[uuid.UUID, tuple[bool, int]], *ids: uuid.UUID
) -> None:
    for eid in ids:
        _require(after[eid] == before[eid], f"{eid} must be untouched: {before[eid]} -> {after[eid]}")


def _require(condition: bool, message: str) -> None:
    """A harness failure is an ``AssertionError`` raised explicitly: pytest reports it as a
    failure, and it survives ``-O`` and Bandit's B101, which a bare ``assert`` does not."""
    if not condition:
        raise AssertionError(message)
