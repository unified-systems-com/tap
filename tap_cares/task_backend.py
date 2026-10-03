"""tap_cares Steady Queue recurring-task declarations.

Replaces the prior `tap_cares/huey_tasks.py`. The single recurring task
declared here is the once-per-minute scheduler tick that calls
`tap_cares.services.evaluate_tick()`. The Steady Queue supervisor's
scheduler dispatches it on the `scheduler` queue, which is served by a
dedicated worker process so a backed-up collector pool cannot starve the
clock (see `tap_cares/specs/spec-tap-cares-task-backend.md`
`req-tap-cares-task-backend-queue-isolation`).

**Single-`@recurring` rule.** This module declares exactly one
`@recurring`-decorated task. Future scheduling needs always route through
the on-grid `Schedule` entity, never through new `@recurring` decorators.
The rule is enforced by `tap_cares/tests/test_recurring_uniqueness.py`
(req-tap-cares-task-backend-recurring-scope-4).
"""

from __future__ import annotations

import logging

from django.tasks import task
from steady_queue.recurring_task import recurring

logger = logging.getLogger(__name__)


@recurring(
    schedule="* * * * *",
    key="tap_cares_scheduler_tick",
    queue_name="scheduler",
    description="TAP scheduler — evaluates on-grid Schedule entities every minute.",
)
@task()
def scheduler_tick() -> None:
    """Once-per-minute scheduler evaluation tick.

    TAP-IMPLEMENTS: req-tap-cares-scheduler-tick@e566a2a46927/80b750807902 (derivation) — the
        once-per-minute recurring tick that evaluates schedules.

    Defers all logic to `tap_cares.services.evaluate_tick()`. A failing tick is logged and
    swallowed — one bad tick must not stop the next one — but **"cannot run at all" is not a bad
    tick and no longer reports success.**

    Two failures were one before 2026-09-30, and conflating them cost three months of silence.
    `evaluate_tick` raising is a bad tick: transient, per-schedule, and the next tick may well
    succeed, so swallowing it is right and is why the broad catch is here. Failing to resolve this
    task's own identity is a broken installation: every tick will fail identically forever, and
    nothing about waiting helps. The old code returned normally for both, so the task framework
    recorded `state=SUCCESSFUL` on a scheduler that had fired nothing for the life of the
    container, with the only trace in a container log that is discarded unless something else
    fails. See `docs/postmortems/2026-09-30-scheduler-tick-raises-and-reports-success.md`.

    So `MissingActor` now propagates: the task is recorded FAILED, which is true, and the recurring
    schedule is untouched, so the next tick still fires. The invariant that one bad tick must not
    stop the next one is preserved — it was never the thing that required lying about the outcome.
    `auth.builtin_actors` in `tap_auth/health.py` is the same fact asserted a layer up, before a
    tick has to discover it.

    **Not covered by a unit test, and the reason is itself the finding.** This module cannot be
    imported under `tap.test_settings` — `@recurring` raises `AttributeError: 'Task' object has no
    attribute 'serialize'` there, on `main` as much as here — so no test can invoke `scheduler_tick`
    at all. `tap_cares/tests/test_no_request_actor.py` reproduces this body rather than calling it,
    which is precisely how a defect in the real function survived unnoticed. The behaviour is
    asserted a layer up instead, by `auth.builtin_actors`.
    """
    # Import lazily so the module is importable in Django startup contexts
    # where the tap_cares app graph isn't fully ready yet.
    from tap_auth.actors import SCHEDULER, acting_as, get_builtin_actor
    from tap_cares.services import evaluate_tick

    # The tick is a background task with no request/ambient actor. It declares its
    # identity — the tap_cares.scheduler program actor — so evaluate_tick's capability
    # gate (cares.run_scheduler) authorizes a real caller, rather than the boundary
    # inventing its own identity (spec-service-layer-boundary.md; the caller-binds model
    # run_collection already uses for its trigger gate).
    # Resolved OUTSIDE the try: a missing identity is a broken installation, not a bad tick, and
    # must not be swallowed into a successful-looking return (see the docstring). MissingActor
    # carries its own remedy — `manage.py sync_auth` — so the raised error is actionable as it
    # stands and needs no re-wrapping here.
    actor = get_builtin_actor(SCHEDULER)

    try:
        with acting_as(actor):
            fires = evaluate_tick()
    except Exception:  # noqa: BLE001 — a bad tick is logged and swallowed; the next one still runs.
        logger.exception("[5985] scheduler_tick: evaluate_tick raised")
        return

    if fires:
        logger.info("[5d7f] scheduler_tick: produced %d fire(s)", len(fires))
