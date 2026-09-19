"""On-by-default enforcement: the @requires_capability decorator + structural
backstops (req-tap-auth-policy On By Default).

Two layers make authorization the *default* state rather than something a
developer must remember:

1. `@requires_capability(cap)` decorates a public service function. It resolves
   the `CallerContext` (explicit arg → contextvar) and calls `authorize()`
   before the function body runs. The default state of a newly-written guarded
   function is therefore "gated."

2. The structural backstops — `assert_write_authorized()` (called at the
   write-pipeline commit chokepoint) and `assert_read_authorized()` (called at
   the Search read-dispatch chokepoint) — re-check, *statelessly*, that the
   active actor holds the capability the operation requires (`policy.can`). An
   operation that reaches commit/return with an actor lacking that capability (or
   no actor) raises `UnguardedOperation` and **fails closed in every mode**.
   There is no decision ledger (req-tap-auth-policy-8): the backstop is
   independent defense-in-depth, not a record of whether `authorize()` ran, and
   when it trips it carries the full stack of the ungated callsite. This is the
   Oso-style "authorize-can-be-forgotten" net: enforced by structure, not
   reviewer vigilance.

`TAP_TEST_MODE` does not gate enforcement — it only raises the volume (the
unguarded callsite is surfaced for CI). Security behavior never depends on test
mode.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import traceback
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, TypeVar

from tap_auth import capabilities as caps
from tap_auth import policy
from tap_auth.errors import UnguardedOperation
from tap_auth.models import UserKind
from tap_grid.write_guard import WRITE_SCOPE_CAPABILITIES, reconcile_write_active, service_write_scope

if TYPE_CHECKING:
    from tap_grid.caller_context import CallerContext

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _resolve_caller_context(kwargs: dict[str, Any]) -> CallerContext | None:
    """Resolve the active CallerContext for authorization.

    An explicit `caller_context` kwarg with an actor wins. If there is no kwarg,
    fall back to the contextvar (set at a request/task/boot/test boundary). If the
    kwarg carries a batch scope but *no* actor, inherit the ambient actor while
    keeping the caller's batch scope — "set a batch_id, run as the current actor."
    """
    explicit = kwargs.get("caller_context")
    if explicit is not None and explicit.user is not None:
        return explicit  # type: ignore[no-any-return]

    from tap_grid.caller_context import get_caller_context

    ambient = get_caller_context()
    if explicit is None:
        return ambient
    if ambient is not None and ambient.user is not None:
        from tap_grid.caller_context import CallerContext

        return CallerContext(user=ambient.user, batch_id=explicit.batch_id)
    return explicit  # type: ignore[no-any-return]


def requires_capability(capability: str, *, operation: str = "") -> Callable[[F], F]:
    """Gate a public service function on one capability.

    Authorizes `capability` for the resolved CallerContext, then runs the
    function. A directly-called write/read that bypassed the decorator is still
    caught by the stateless backstop, which re-checks the actor's capability at
    the commit/dispatch chokepoint.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = _resolve_caller_context(kwargs)
            policy.authorize(ctx, capability, operation=operation or fn.__name__)
            # A gated write function opens the service-write scope for its body, so
            # its node/edge writes pass the write backstop (req-tap-auth-write-batch-
            # routing). Reads (grid.read) do not open it.
            if capability in WRITE_SCOPE_CAPABILITIES:
                with service_write_scope():
                    return fn(*args, **kwargs)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def gates_per_operation(fn: F) -> F:  # noqa: UP047 — module uses the F TypeVar style throughout
    """Marker: a public service function that authorizes *per operation* in its
    body rather than via a single static ``@requires_capability``.

    Used only where one static capability genuinely cannot express the
    requirement — the canonical case is ``write_batch``, whose batch may mix
    create/update ops (need ``grid.write``) and delete ops (need ``grid.delete``),
    each authorized at dispatch via ``assert_write_authorized``. The gateway
    coverage lint (``test_service_gateway_coverage``) accepts this marker in lieu
    of ``@requires_capability`` so a per-op-gated function is not mistaken for an
    ungated one. It is a no-op at runtime beyond stamping a detectable attribute;
    reach for it sparingly — a static gate is always preferred when it fits.
    """
    fn.__tap_gates_per_operation__ = True  # type: ignore[attr-defined]
    return fn


@contextlib.contextmanager
def authorized(
    caller_context: CallerContext | None,
    capability: str,
    *,
    operation: str = "",
    resource_type: str = "",
    resource: Any = None,
) -> Iterator[None]:
    """Authorize `capability`, then run the body.

    The decorator form (`@requires_capability`) is preferred for plain functions
    that take a `caller_context`. This context-manager form is for entry points
    that resolve their actor differently — e.g. `grift_import`, which takes an
    `actor` argument rather than a `caller_context`. The body's writes/reads are
    backed by the stateless backstop, which re-checks the actor's capability at
    the commit/dispatch chokepoint.
    """
    policy.authorize(
        caller_context,
        capability,
        operation=operation,
        resource_type=resource_type,
        resource=resource,
    )
    # Same as the decorator: a write-class authorization opens the service-write
    # scope for the body (e.g. grift_import runs under `authorized(grid.import_grift)`).
    if capability in WRITE_SCOPE_CAPABILITIES:
        with service_write_scope():
            yield
    else:
        yield


def _callsite(skip: int = 2) -> str:
    """Best-effort callsite of the code that reached the unguarded chokepoint."""
    stack = traceback.extract_stack()
    # Walk outward past this module's frames to the first non-tap_auth frame.
    for frame in reversed(stack[:-skip]):
        if "/tap_auth/" not in frame.filename:
            return f"{frame.filename}:{frame.lineno} in {frame.name}"
    return "<unknown>"


def _raise_unguarded(kind: str, caller_context: CallerContext | None, detail: str) -> None:
    """Emit the class-aware security Flaw and raise UnguardedOperation (fail closed).

    The blame class (`code` vs `app`) is decided from the offending callsite: a
    read/write that skipped the authorize gate from a plugin is an `app` Flaw, from
    first-party code a `code` Flaw. `report_service_layer_bypass` locates that
    callsite and emits the `unguarded_operation` Flaw before we fail closed.
    """
    from tap.flaws import report_service_layer_bypass

    user = caller_context.user if caller_context is not None else None
    callsite = _callsite()
    report_service_layer_bypass(
        invariant_id="unguarded_operation",
        message=f"unguarded {kind} operation — no authorize() decision recorded; failing closed",
        logger=logger,
        kind=kind,
        detail=detail,
        actor=getattr(user, "username", None),
    )
    raise UnguardedOperation(f"unguarded {kind}: no authorization decision recorded before {detail}", callsite=callsite)


def assert_write_authorized(
    caller_context: CallerContext | None,
    *,
    needs_write: bool = True,
    needs_delete: bool = False,
) -> None:
    """Backstop at the write-pipeline commit chokepoint, per op-class.

    A batch containing create/update ops requires the actor to hold `grid.write`;
    a batch containing delete ops *additionally* requires `grid.delete` — a plain
    `grid.write` holder cannot carry a delete (req-tap-auth-policy On By Default).
    Stateless re-check (`policy.can`): if the actor reaching commit does not hold
    the capability its ops require (or there is no actor), the mutation fails
    closed. The DELETE check requires `grid.delete` specifically — broad covers
    (`grid.import_grift`, `grid.admin`) do not satisfy it, so a bootloader or
    collector cannot tombstone through an import cover. The one exception is
    narrow and scoped, not broad: inside the reconcile verb's apply pass
    (`tap_grid.write_guard.reconcile_write_scope`), `grid.reconcile` licenses the
    verb's own tombstones (req-grid-reconcile-verb) — the collector actor holds
    `grid.reconcile` and not `grid.delete`, and outside that scope it still cannot
    delete anything.
    """
    if needs_write and not policy.can(caller_context, caps.WRITE_CAPABILITY):
        _raise_unguarded("write", caller_context, "write_batch commit")
    if needs_delete and not policy.can(caller_context, caps.DELETE_CAPABILITY):
        if reconcile_write_active() and policy.can(caller_context, caps.RECONCILE_CAPABILITY):
            return
        _raise_unguarded("delete", caller_context, "write_batch delete op")


def assert_read_authorized(caller_context: CallerContext | None, *, detail: str = "search dispatch") -> None:
    """Backstop at a graph-read chokepoint.

    Passes iff the active actor holds `grid.read` (stateless `policy.can`
    re-check). Otherwise the read reached the chokepoint with an unauthorized or
    missing actor — fail closed (returns no data).

    Args:
        detail: The read site, woven into the failure message and log. Defaults to
            the Search read-dispatch chokepoint; the ORM read backstop
            (`tap_grid.read_guard`) passes the offending model/statement instead.
    """
    if policy.can(caller_context, caps.READ_CAPABILITY):
        return
    _raise_unguarded("read", caller_context, detail)


def assert_program_actor(caller_context: CallerContext | None, *, operation: str) -> None:
    """Backstop: `operation` may run only under a named PROGRAM actor, not a human.

    Guards the INTERNAL_ONLY write bypass (`write_batch(..., _internal_only_bypass=
    True)`) — the trusted-internal door that writes INTERNAL_ONLY node types
    (CollectionJob, Collector, ScheduleFire, Batch, ...) the public service path
    rejects. With named program actors now first-class (req-tap-auth-actor-model),
    that door is bound to them by construction: every legitimate user of the bypass
    runs as a program actor (the collector/scheduler runtimes, boot), so a human
    actor — or none — reaching it means an upstream program-actor swap was forgotten.
    That is a defect, not a denial, so it fails closed in every mode like the
    write/read backstops, and `TAP_TEST_MODE` only raises the volume.

    Belt-and-suspenders to the type-level INTERNAL_ONLY gate: the gate stops the
    public path, this binds the trusted bypass to program identity. A future
    refinement narrows it further — which entity *types* each actor may create —
    once that per-actor model exists.
    """
    user = caller_context.user if caller_context is not None else None
    if user is not None and getattr(user, "user_kind", None) == UserKind.PROGRAM:
        return

    callsite = _callsite()
    actor_kind = getattr(user, "user_kind", None)
    logger.error(
        "[db93] UNGUARDED internal-only write — %s requires a program actor; actor=%s kind=%s. "
        "Failing closed; an upstream program-actor swap was likely forgotten. callsite=%s",
        operation,
        getattr(user, "username", None),
        actor_kind,
        callsite,
        stack_info=True,
        extra={
            "message_data": {
                "flaw_class": "code",
                "flaw_tags": ["security"],
                "operation": operation,
                "actor_kind": actor_kind,
                "callsite": callsite,
            }
        },
    )
    raise UnguardedOperation(
        f"{operation} requires a program actor; got actor kind {actor_kind!r}",
        callsite=callsite,
    )
