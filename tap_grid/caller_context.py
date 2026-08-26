"""CallerContext — the typed carrier for actor identity and batch scope.

Every public service-layer function accepts a CallerContext. It carries:
  - user: the acting named actor. Under the on-by-default service-boundary
    enforcement (req-tap-auth-policy), a public read/write requires a named actor;
    `user=None` is rejected (MissingActor). System-initiated work runs as a named
    program actor (tap_bootloader / tap_cares.collector / tap_cares.scheduler), never None.
    The field may be None only below the service boundary (model-level saves,
    migrations) and is resolved/inherited from the active context where possible.
  - batch_id: an existing batch scope to join (None means the service layer generates one)

A module-level ContextVar holds the active CallerContext so that BaseModel.save()
can read batch_id without requiring a signature change to Django's save() machinery.

A second ContextVar carries the deferred-hotlink-check queue used by multi-op
batches to push hotlink validation past the per-row save (where edges from the
same batch have not yet landed) to the post-loop / pre-commit consistency phase.
See req-grid-hotlink-deferred and req-grid-service-batch-precommit-consistency.

See: req-grid-service-pipeline-context
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Typed against Django's AbstractUser base, not the concrete tap_auth.User —
    # the grid caller context stays generic over AUTH_USER_MODEL
    # (req-tap-auth-user-model-5).
    from django.contrib.auth.models import AbstractUser

    from tap_grid.models import BaseModel

_caller_context: contextvars.ContextVar[CallerContext | None] = contextvars.ContextVar(
    "caller_context",
    default=None,
)


@dataclass(frozen=True)
class CallerContext:
    """Typed carrier for actor identity and batch scope.

    Frozen to prevent accidental mutation inside the write pipeline.

    Attributes:
        user: The acting named actor. A public service read/write requires a
            non-None actor under the on-by-default enforcement; `None` is rejected
            at the boundary (system work uses a named program actor). None remains
            valid only below the service layer (model-level saves).
        batch_id: An existing batch scope to join. None means the service
            layer will generate a new batch_id for this operation.
    """

    user: AbstractUser | None = None
    batch_id: str | None = None


def get_caller_context() -> CallerContext | None:
    """Return the active CallerContext for the current execution context, or None."""
    return _caller_context.get()


def set_caller_context(ctx: CallerContext | None) -> None:
    """Set the active CallerContext for the current execution context."""
    _caller_context.set(ctx)


def require_caller_context() -> CallerContext:
    """Return the active CallerContext, or raise if none is bound.

    TAP-IMPLEMENTS: req-grid-service-pipeline-context@95d60312f607/2b5d5a28e5ff (derivation) — the one
        accessor for request identity. A route consumes this rather than rebuilding a
        context from `request.user`; two definitions of "who is calling" on an
        authorization surface is how the predicates silently diverged.

    The accessor for **request-scoped** code (API routes, web views): the context
    bound by `CallerContextMiddleware` is the single source of request identity,
    so a route consumes it rather than rebuilding one from `request.user`. Four
    hand-rolled rebuilders previously did the latter with a *different*
    authenticated-vs-anonymous predicate than the middleware's — two definitions
    of "who is calling" on an authorization surface (the 2026-08 derive-the-same-
    fact-twice audit, finding #4).

    Fails closed: a real request always has a context (the middleware binds one
    for every request, `user=None` for anonymous), so an unbound context means
    the code ran outside the middleware — a wiring bug that must be loud, never
    silently papered over with an invented identity.

    Raises:
        NoCallerContextError: No CallerContext is bound in this execution context.
    """
    ctx = _caller_context.get()
    if ctx is None:
        from tap_grid.exceptions import NoCallerContextError

        raise NoCallerContextError(
            "no active CallerContext — request-scoped code must run under "
            "CallerContextMiddleware, which binds the request's identity "
            "(req-grid-service-pipeline-context)"
        )
    return ctx


# ---------------------------------------------------------------------------
# Deferred hotlink check queue (req-grid-hotlink-deferred)
# ---------------------------------------------------------------------------
#
# Carried separately from CallerContext because CallerContext is frozen. The
# queue holds BaseModel instance references — the same instances that the
# per-op pipeline validated and saved. Holding the instance (rather than just
# entity_id) lets the drain re-run validate_hotlinks() directly without an
# extra DB roundtrip and side-steps the fresh-create-id-is-unset case (the
# pipeline assigns entity_id during save, so by drain time the instance carries
# the assigned id). When the ContextVar is None the deferred mode is inactive
# and validate_hotlinks() runs inline as defined in req-grid-hotlink-validation.

_pending_hotlink_checks: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
    "pending_hotlink_checks",
    default=None,
)


def start_deferred_hotlink_checks() -> contextvars.Token[list[Any] | None]:
    """Activate deferred-hotlink mode for the current execution context.

    Subsequent calls to validate_hotlinks() enqueue the instance instead of
    validating inline. Returns a Token suitable for reset_deferred_hotlink_checks().
    Nested re-entry overwrites with a fresh empty queue; the returned Token
    preserves the previous queue (if any) on reset.
    """
    return _pending_hotlink_checks.set([])


def reset_deferred_hotlink_checks(token: contextvars.Token[list[Any] | None]) -> None:
    """Restore the prior deferred-hotlink state (typically: None / inactive)."""
    _pending_hotlink_checks.reset(token)


def is_deferring_hotlinks() -> bool:
    """Return True iff deferred-hotlink mode is active for this context."""
    return _pending_hotlink_checks.get() is not None


def enqueue_deferred_hotlink_check(instance: BaseModel) -> None:
    """Append an instance to the deferred-hotlink queue.

    No-op if deferred mode is not active (defensive — callers should check
    is_deferring_hotlinks() before calling, but validate_hotlinks() relies on
    this safety to keep the inline path branch-free).
    """
    queue = _pending_hotlink_checks.get()
    if queue is None:
        return
    queue.append(instance)


def drain_deferred_hotlink_checks() -> list[Any]:
    """Return the current deferred queue and deactivate deferred mode.

    The returned list is the queue's content at call time. The ContextVar is
    set to None so the deferred mode is OFF after the drain: any further
    validate_hotlinks() calls (in particular, the ones the drain itself makes
    when re-validating each instance) run inline against the now-current edge
    set rather than feeding back into the queue we just drained.

    The surrounding write_batch frame still owns the start/reset token pair,
    so reset_deferred_hotlink_checks(token) at the end restores the prior
    (typically None) state cleanly.
    """
    queue = _pending_hotlink_checks.get()
    if queue is None:
        return []
    _pending_hotlink_checks.set(None)
    return queue
