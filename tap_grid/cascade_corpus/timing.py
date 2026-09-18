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
from typing import Any

from django.db import connection, transaction

from tap_grid.cascade_corpus.runner import event_counts, event_delta, latest_event, snapshot
from tap_grid.models import BatchEvent, BatchEventType, Entity
from tap_grid.services import create_edge, create_node

__all__ = [
    "JOIN_SECONDS",
    "NESTS",
    "NODE",
    "Outcome",
    "bumped_once",
    "contains",
    "deletes_on",
    "event_counts",
    "event_delta",
    "finish",
    "hold_lock_then",
    "in_thread",
    "latest_event",
    "live",
    "lost_a_deadlock",
    "node",
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
        assert not thread.is_alive(), "a writer never finished — a deadlock or an unreleased lock"
        assert outcome.error is None, f"writer raised: {outcome.error!r}"


def hold_lock_then(entity_id: uuid.UUID, locked: threading.Event, go: threading.Event, then: Callable[[], Any]) -> Any:
    """In one transaction: lock the row, say so, wait for the signal, run ``then``, commit."""
    with transaction.atomic():
        Entity.objects.select_for_update().get(pk=entity_id)
        locked.set()
        assert go.wait(JOIN_SECONDS), "the test never released the lock holder"
        return then()


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
    """Every id is retired and its version moved exactly once."""
    for eid in ids:
        assert after[eid][0], f"{eid} should be retired"
        assert after[eid][1] == before[eid][1] + 1, f"{eid} version {before[eid][1]} -> {after[eid][1]}: exactly once"


def untouched(
    before: dict[uuid.UUID, tuple[bool, int]], after: dict[uuid.UUID, tuple[bool, int]], *ids: uuid.UUID
) -> None:
    for eid in ids:
        assert after[eid] == before[eid], f"{eid} must be untouched: {before[eid]} -> {after[eid]}"
