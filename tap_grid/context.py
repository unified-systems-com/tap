"""Grid-level context helpers — batch_id access through CallerContext.

These helpers are kept for backward compatibility. Both delegate to
tap_grid.caller_context, which is the canonical location for execution context.

New code should use get_caller_context() / set_caller_context() directly.
Existing code that calls get_batch_id() / set_batch_id() continues to work.
"""

from dataclasses import replace

from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context


def set_batch_id(batch_id: str | None) -> None:
    """Set the batch_id in the active CallerContext.

    If a CallerContext is already active, everything but its batch scope is
    preserved — its actor, and its batch label (req-grid-service-batch-label-required).
    If none exists, an actor-less context is created — but note that under the
    on-by-default enforcement a public service read/write then requires the
    actor to be resolved (a None actor is rejected at the boundary).
    """
    current = get_caller_context()
    set_caller_context(replace(current, batch_id=batch_id) if current else CallerContext(batch_id=batch_id))


def get_batch_id() -> str | None:
    """Return the batch_id from the active CallerContext, or None."""
    ctx = get_caller_context()
    return ctx.batch_id if ctx else None
