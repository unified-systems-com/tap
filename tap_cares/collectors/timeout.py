"""run_with_ceiling — a wall-clock ceiling for one blocking call, for any collector.

req-tap-cares-collector-call-ceiling (spec-tap-cares-collector.md).

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


def run_with_ceiling(fn: Callable[[], T], ceiling: float) -> T:
    """Run ``fn()`` with an aggregate wall-clock deadline; raise ``CeilingExceeded`` past it.

    ``fn`` takes no arguments — bind whatever it needs with a closure or ``functools.partial``
    before calling. A ceiling of zero or less means the deadline has already passed.
    """
    if ceiling <= 0:
        raise CeilingExceeded("deadline passed before the attempt")
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=_run, name="run-with-ceiling", daemon=True)
    worker.start()
    worker.join(timeout=ceiling)
    if worker.is_alive():
        raise CeilingExceeded(f"call ceiling {ceiling:.0f}s exceeded")
    if "error" in box:
        raise box["error"]
    return cast(T, box["result"])
