"""Structural read backstop for TAP-managed graph data (req-tap-auth-policy).

Companion to the write backstop (`assert_write_authorized`, at the write-pipeline
commit chokepoint) and the Search read backstop (`assert_read_authorized`, at the
Search dispatch chokepoint). Those guard code that goes *through* the service
layer. This module guards the layer *below* them — the Django ORM itself — so a
caller that reaches TAP-managed rows without crossing the service boundary (a web
view or API route that forgot to authorize `grid.read`) fails closed instead of
leaking rows.

Two enforcement points, one predicate:

- **Layer 1 — `BaseModelQuerySet._fetch_all`.** Every materialization of a
  TAP-managed queryset (`.get()`, `.first()`, iteration, `list(...)`, `values()`)
  funnels through `_fetch_all`. Overriding it there is model-aware (the error
  names the model) and covers every `BaseModel` subclass — including `Edge` — for
  free, because they all share this one QuerySet class.
- **Layer 2 — a `connection.execute_wrapper`.** `_fetch_all` does not see
  `.count()`, `.exists()`, `.aggregate()`, `.raw()`, or direct cursor SQL. The SQL
  wrapper is the completeness net: it inspects every statement and enforces the
  same predicate when a *read* touches a guarded table. It also covers
  `EntityType` (the plugin/type catalog), which is not a `BaseModel` and so is
  invisible to Layer 1 — closing the metadata-catalog gap.

The predicate (`enforce_managed_read`) is capability-based, matching the existing
backstops rather than tracking "was authorize() called":

- **bypass active** → allow. `unguarded_read()` is the explicit escape hatch for
  sanctioned direct-ORM consumers below/around the service boundary (management
  commands, low-level model tests, internal maintenance). Django admin is not one:
  it authorizes `grid.read` like any other web surface (req-tap-auth-policy-6).
- **no CallerContext at all** (`get_caller_context() is None`) → allow. This is
  the out-of-scope infrastructure zone that CLAUDE.md sanctions for direct ORM
  (migrations, `manage.py shell`, ad-hoc commands). A real request always carries
  a context (CallerContextMiddleware binds one for *every* request, `user=None`
  for anonymous), and every service operation sets one — so the finding class
  (an authenticated, capability-less user reading via a web/API route) is always
  caught: its context is present but lacks `grid.read`.
- **context present** → the active actor must hold `grid.read` (stateless
  `policy.can` re-check). Otherwise fail closed via `assert_read_authorized`,
  which emits the loud security log and raises `UnguardedOperation`.

`Entity` (the spine) and the simple_history tables of every classified model are
guarded too, since Issue# 963 - tap: the spine's exemption rested on an Entity API
that no longer exists, and history is graph data. Not covered here (named open
edge): the ctx-None infrastructure zone above. See req-tap-auth-orm-read-backstop.
"""

from __future__ import annotations

import contextlib
import contextvars
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tap_grid.caller_context import CallerContext

# When True, the read backstop is suspended for the current execution context.
# Explicit, narrow escape hatch for sanctioned direct-ORM readers (see module
# docstring). Also set transiently around the capability re-check itself so the
# auth-table SELECTs it issues cannot re-enter the guard.
_read_guard_bypass: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "read_guard_bypass",
    default=False,
)

# Per-context memo of the grid.read decision, keyed by the active CallerContext
# identity. The capability check is an explicit Permission⋈Group⋈User query; the
# ORM chokepoint fires on every read, so without this a request would pay one
# authz query per row-fetch. A fresh CallerContext (one per request/operation)
# invalidates the memo by identity.
_read_grant_memo: contextvars.ContextVar[tuple[object, bool] | None] = contextvars.ContextVar(
    "read_grant_memo",
    default=None,
)


@contextlib.contextmanager
def unguarded_read() -> Iterator[None]:
    """Suspend the TAP-managed read backstop for the wrapped block.

    For sanctioned direct-ORM consumers below/around the service boundary only —
    management commands, low-level model tests, internal maintenance.
    NOT for above-service-layer application code: web views, Django admin and API
    routes must authorize `grid.read` (which flows an actor that holds it into the
    context), not reach for this hatch.
    """
    token = _read_guard_bypass.set(True)
    try:
        yield
    finally:
        _read_guard_bypass.reset(token)


def _actor_may_read(ctx: CallerContext) -> bool:
    """Memoized `policy.can(ctx, grid.read)` for the active context.

    The `policy.can` call issues auth-table SELECTs; those must not re-enter the
    guard (infinite recursion), so it runs under the bypass. Auth tables are not
    guarded tables anyway, but the bypass also skips the per-statement work.
    """
    memo = _read_grant_memo.get()
    if memo is not None and memo[0] is ctx:
        return memo[1]

    from tap_auth import policy
    from tap_auth.capabilities import READ_CAPABILITY

    token = _read_guard_bypass.set(True)
    try:
        allowed = policy.can(ctx, READ_CAPABILITY)
    finally:
        _read_guard_bypass.reset(token)

    _read_grant_memo.set((ctx, allowed))
    return allowed


def caller_can_read() -> bool:
    """True iff a guarded read by the current caller would be permitted.

    Mirrors `enforce_managed_read`'s allow predicate exactly, but performs no
    read and never raises — it answers the question the backstop would ask,
    ahead of time. Presentation code that renders on *every* request (chrome,
    context processors) uses this to decide whether to run a graph read at all,
    degrading to a read-free rendering when the caller lacks `grid.read` rather
    than tripping the backstop mid-render (which would 500 the page). This keeps
    the always-present shell safe for anonymous / capability-less renders while
    the enriched read stays gated for authorized callers.

    Allow when: the bypass is active, OR there is no CallerContext (the
    out-of-scope infrastructure zone — migrations / shell / commands), OR the
    active actor holds `grid.read`.
    """
    if _read_guard_bypass.get():
        return True

    from tap_grid.caller_context import get_caller_context

    ctx = get_caller_context()
    if ctx is None:
        return True
    return _actor_may_read(ctx)


def enforce_managed_read(detail: str) -> None:
    """Backstop a read of TAP-managed graph data. Fail closed if unauthorized.

    See the module docstring for the allow/deny predicate. On denial, delegates to
    `assert_read_authorized`, which emits the structured security log and raises
    `UnguardedOperation` (fails closed in every mode).

    Args:
        detail: Human-readable read site (e.g. ``orm read tap_web.Panel``), woven
            into the failure message and log so the forgotten gate is locatable.
    """
    if _read_guard_bypass.get():
        return

    from tap_grid.caller_context import get_caller_context

    ctx = get_caller_context()
    if ctx is None:
        # Out-of-scope infrastructure zone (migrations / shell / commands).
        return
    if _actor_may_read(ctx):
        return

    from tap_auth.enforcement import assert_read_authorized

    assert_read_authorized(ctx, detail=detail)


# ---------------------------------------------------------------------------
# Layer 2 — SQL execute_wrapper (completeness net)
# ---------------------------------------------------------------------------

_guarded_regex_cache: re.Pattern[str] | None = None


def _guarded_regex() -> re.Pattern[str]:
    """Compiled alternation matching a quoted guarded-table identifier in SQL.

    The guarded set comes from the shared single source of truth
    (`tap_grid.grid_tables.read_guarded_tables`): every classified table — every
    concrete `BaseModel` table, the `Entity` spine and the `EntityType` catalog —
    and the history table of each. Computed once and cached — the model set is
    fixed at process start.
    """
    global _guarded_regex_cache
    if _guarded_regex_cache is not None:
        return _guarded_regex_cache

    from tap_grid.grid_tables import read_guarded_tables

    alternation = "|".join(re.escape(t) for t in sorted(read_guarded_tables()))
    _guarded_regex_cache = re.compile(f'"({alternation})"')
    return _guarded_regex_cache


def _is_guarded_read(sql: str) -> bool:
    """True iff `sql` is a read statement touching a guarded table.

    Only SELECT/WITH (read) statements are considered here — writes are backstopped
    at the service-layer commit chokepoint (`assert_write_authorized`). Called only
    for a context that lacks `grid.read`, so the table scan is off the hot path for
    authorized callers.
    """
    head = sql[:8].lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False
    return _guarded_regex().search(sql) is not None


def _read_sql_wrapper(
    execute: Any,
    sql: str,
    params: Any,
    many: bool,  # noqa: FBT001
    context: Any,
) -> Any:
    """execute_wrapper enforcing the read backstop on guarded-table reads.

    Ordering is chosen so authorized callers pay almost nothing: bypass and
    absent-context short-circuit first, then the memoized capability check. Only a
    context that lacks `grid.read` reaches the SQL/table inspection — and it is
    blocked on the first guarded read it attempts.
    """
    if not _read_guard_bypass.get():
        from tap_grid.caller_context import get_caller_context

        ctx = get_caller_context()
        if ctx is not None and not _actor_may_read(ctx) and _is_guarded_read(sql):
            enforce_managed_read("orm sql read")
    return execute(sql, params, many, context)


def install_read_sql_guard(connection: Any, **_kwargs: Any) -> None:
    """Attach the read-guard execute_wrapper to a DB connection (idempotent).

    Wired to Django's `connection_created` signal so every connection — request,
    task, management command, or shell — carries the guard without a registration
    step that could be forgotten.
    """
    if _read_sql_wrapper not in connection.execute_wrappers:
        connection.execute_wrappers.append(_read_sql_wrapper)
