"""Structural write backstop: node/edge writes must route through the service layer.

The architectural rule (CLAUDE.md, spec-grid-service): every mutation of a
TAP-managed node or edge goes through the service layer (`write_batch` and the
`@requires_capability`-gated `create_node`/`patch_node`/`create_edge`/`delete_*`/
`purge_*` functions), so it carries batch scope, FLIP, provenance, and the
`grid.write`/`grid.delete`/`grid.purge` authorization backstop. A direct
`instance.save()` / `Model.objects.create()` / `entity.delete()` from a view,
panel, collector, or command bypasses all of that.

This is the write analog of the read backstop (`tap_grid/read_guard.py`), and it
converts that rule from convention into a runtime invariant. Unlike the read
guard (capability-based: "does the actor hold grid.read"), the write guard is
*scope-based*: a node/edge write is permitted only when it happens **inside a
service-layer write scope** — a contextvar opened by the sanctioned write API:

- `requires_capability` / `authorized` (tap_auth) open the scope for their body
  when the authorized capability is write-class (grid.write / grid.delete /
  grid.purge / grid.import_grift) — so every gated service write function opens it
  by construction, current and future.
- `write_batch` opens it directly (it is the commit chokepoint and is not itself
  decorated).

`BaseModel.save`/`delete` and `Entity.save`/`delete` call `enforce_service_write`,
which fails closed (`UnguardedOperation`, a defect-class error → 500, not a user
denial) when a write reaches the ORM outside any such scope. Capability
enforcement still happens at the gate (`@requires_capability`) and the write
backstop (`assert_write_authorized`); this guard adds the "and it went through the
batch pipeline at all" half.

Exemptions:
- `unguarded_write()` — explicit escape hatch for sanctioned direct-ORM writers
  below/around the service boundary (low-level model tests, admin/infra, one-off
  maintenance). The test suite wraps itself in this (tests are the sanctioned
  below-service zone, like migrations).
- Migrations are exempt automatically: migration-state/historical models are
  reconstructed without the `BaseModel`/`Entity` method overrides, so they never
  reach this guard.

See req-tap-auth-write-batch-routing.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Capabilities whose authorization means "we are entering a sanctioned service
# write" — authorizing any of these opens the write scope for the gated body.
# TAP-KNOWN-DUPE(write-scope-caps): the canonical spellings are the *_CAPABILITY
# constants in tap_auth/capabilities.py — this module cannot import them at module
# scope because tap_auth.enforcement imports THIS module at module scope (the
# deferred tap_auth import at the bottom of this file exists for the same reason).
# Editing this set means putting eyes on the partner constants.
WRITE_SCOPE_CAPABILITIES: frozenset[str] = frozenset({"grid.write", "grid.delete", "grid.purge", "grid.import_grift"})

# True while control is inside a service-layer write scope (nestable — token-based
# set/reset, so an inner scope restores the outer's value on exit).
_service_write_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "service_write_active",
    default=False,
)

# True while the write guard is explicitly suspended (the escape hatch).
_write_guard_bypass: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "write_guard_bypass",
    default=False,
)


@contextlib.contextmanager
def service_write_scope() -> Iterator[None]:
    """Mark the wrapped block as a sanctioned service-layer write.

    Node/edge writes (`BaseModel`/`Entity` `save`/`delete`) inside this scope pass
    the write guard. Opened by the service write API — application code should not
    call this directly; it should call the service layer, which opens it.
    """
    token = _service_write_active.set(True)
    try:
        yield
    finally:
        _service_write_active.reset(token)


@contextlib.contextmanager
def unguarded_write() -> Iterator[None]:
    """Suspend the write guard for the wrapped block (escape hatch).

    For sanctioned direct-ORM writers below/around the service boundary only —
    low-level model tests, admin/infra, one-off maintenance. NOT for
    above-service-layer application code: views, panels, collectors, and commands
    must route writes through the service layer (which opens the scope for them).
    """
    token = _write_guard_bypass.set(True)
    try:
        yield
    finally:
        _write_guard_bypass.reset(token)


def enforce_service_write(detail: str) -> None:
    """Fail closed if a node/edge write is happening outside a service write scope.

    Passes iff the bypass hatch is active or we are inside a `service_write_scope`
    (i.e. the write is going through the sanctioned service-layer pipeline).
    Otherwise raises `UnguardedOperation` — a defect (some code mutated the grid by
    direct ORM instead of the service layer), not a user-facing denial.

    Args:
        detail: The write site (e.g. ``save tap_web.Panel``), woven into the
            failure message so the offending direct write is locatable.
    """
    if _write_guard_bypass.get() or _service_write_active.get():
        return

    from tap.flaws import report_service_layer_bypass
    from tap_auth.errors import UnguardedOperation

    # Emit the class-aware security Flaw before failing closed: `code` if the
    # offending write lives in first-party TAP, `app` if in a plugin — so the
    # blame domain is on the record without anyone reading the stack.
    report_service_layer_bypass(
        invariant_id="grid_write_service_layer_bypass",
        message=f"unguarded write: {detail} bypassed the service layer",
        logger=logger,
        detail=detail,
    )
    raise UnguardedOperation(
        f"unguarded write: {detail} bypassed the service layer — node/edge mutations must go "
        f"through the service layer (write_batch / create_node / create_edge / delete_* / patch_node), "
        f"which carries batch scope, FLIP, provenance, and the grid.write/grid.delete backstop. "
        f"For sanctioned below-service writes (tests, admin, migrations) wrap in "
        f"tap_grid.write_guard.unguarded_write().",
        callsite=detail,
    )
