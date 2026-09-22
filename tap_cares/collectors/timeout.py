"""run_with_ceiling — a wall-clock ceiling for one blocking call, for any collector.

TAP-IMPLEMENTS: req-tap-cares-collector-call-ceiling@83395eb1af71/c596fd439c48 (derivation) — the
    one place the daemon-thread-join ceiling mechanism itself is defined; every collector that
    wants a wall-clock bound on a blocking call goes through this function.

**The constraint this exists for.** A socket timeout (`urllib.request.urlopen(timeout=N)`, most
client libraries' own `timeout=`) bounds inactivity — the gap between bytes — not the whole
attempt. DNS resolution and a slow-trickle response that keeps resetting the inactivity clock can
both outlive it, so a collector making a blocking network call has no wall-clock guarantee unless
something wraps the call itself.

**Why this is a thread, not a signal or a kill.** CPython cannot interrupt or kill a running
thread — there is no cancelling a blocked socket read. `signal.alarm`/`SIGALRM` only fires on a
process's main thread, which a `steady_queue` worker thread is not. Surveyed against Celery,
Dramatiq, RQ, pebble and huey (2026-09-21): every thread-pool-based system either has no hard
timeout at all, or degrades to exactly this pattern — run the attempt on a daemon thread, rejoin
with a timeout, and give up ownership if it is still alive. There is no fourth option inside a
thread-pool worker; a *true* kill needs a process-pool architecture, which `steady_queue` is not.

**The contract this places on the wrapped callable.** An attempt abandoned at the ceiling keeps
running on its own thread until its blocking call eventually returns or errors — it is not killed,
only disowned. The callable must not mutate anything the caller still owns after it returns
(a shared client, a cursor, a cache) until it hands back its result; if it does, that mutation can
land after the ceiling has already moved the caller on. Return a value instead of writing to shared
state from inside the callable.

**This bounds the caller's wait, not the remote effect.** `CeilingExceeded` means the caller gave
up waiting — it does NOT mean the abandoned attempt's remote operation was cancelled; a request
already in flight when the ceiling passes can still complete on the far end. That is safe to ignore
for a read (GitHub's own `github_call.py` wraps only `GET`s and GraphQL queries — no in-repo caller
wraps a mutation as of 2026-09-22). It is NOT safe by default for a write: a `POST`/`PATCH`/`DELETE`
wrapped here can land after `CeilingExceeded` is raised, and a caller that retries on that exception
can then duplicate or reorder the remote effect. Only wrap a mutating call here if it is genuinely
idempotent (a safe-to-repeat PUT, an upsert keyed by a client-supplied id) or the caller has its own
idempotency key / reconciliation strategy for the retry; otherwise give it its own handling instead
of this primitive.

Lifted out of `tap-plugin-github-core`'s `github_call.py::_under_ceiling` (2026-09-21,
unified-systems-com/tap#750) — that module's own budget/retry/failure-classification layers stay
plugin-specific (GitHub's own reliability semantics); only the thread-ceiling mechanism itself was
generic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")


class CeilingExceeded(TimeoutError):
    """The wrapped callable outlived its ceiling; its thread is abandoned, not killed."""


def run_with_ceiling(fn: Callable[[], T], ceiling: float, *, name: str = "run-with-ceiling") -> T:
    """Run ``fn()`` with an aggregate wall-clock deadline; raise ``CeilingExceeded`` past it.

    ``fn`` takes no arguments — bind whatever it needs with a closure or ``functools.partial``
    before calling. A ceiling of zero or less means the deadline has already passed. ``name`` sets
    the abandoned thread's name (visible in ``threading.enumerate()`` and thread dumps) — pass a
    caller-specific one so an abandoned attempt is identifiable by who left it running.

    Only wrap a read or an idempotent write — see the module docstring's "bounds the caller's
    wait, not the remote effect" section before wrapping anything that mutates.
    """
    if ceiling <= 0:
        raise CeilingExceeded("deadline passed before the attempt")
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=_run, name=name, daemon=True)
    worker.start()
    worker.join(timeout=ceiling)
    if worker.is_alive():
        raise CeilingExceeded(f"call ceiling {ceiling:.0f}s exceeded")
    if "error" in box:
        raise box["error"]
    return cast(T, box["result"])
