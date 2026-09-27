"""Runtime resolution and binding of built-in program actors (req-tap-auth-builtins).

System-initiated work — boot, collectors, the scheduler, GRIFT import — runs as a
named `program` actor, never `User=None` (req-tap-auth-actor-model). This module
provides the two halves of that:

  - `get_builtin_actor(key)` resolves an already-synced built-in actor at runtime.
    The actors themselves are created by `tap_auth.sync` (run at boot, by the
    `sync_auth` command, or by the test fixture); resolving one that does not exist
    is a hard error, because it means system-initiated work is running before auth
    bootstrap — the chicken-and-egg the boot ordering (req-tap-auth-boot,
    req-boot-phases) exists to prevent.
  - `acting_as(actor)` binds a resolved actor into the `CallerContext` for the
    duration of a block — the no-request analogue of `CallerContextMiddleware`.
    A no-request subsystem (a Django-Tasks worker, a scheduler tick, the boot
    sequence) has no middleware to bind `request.user`, so it binds its own named
    program actor at its entry boundary; downstream service-layer calls inherit it
    from the contextvar exactly as a request handler's calls inherit the
    middleware-bound user.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model

from tap_auth import sync as _sync
from tap_auth.errors import MissingActor
from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

# Built-in keys for the system program actors. tap_auth.sync is the v0
# authoritative definition (it WRITES the actor rows, req-tap-auth-builtins);
# these names alias its constants so the resolvers here and the writers there
# can never drift apart. Interim wiring: the whole definition moves to the
# per-app declarative program-users file when that pass lands
# (req-tap-auth-program-users) — do not grow a new registry here.
BOOTLOADER = _sync.ACTOR_BOOTLOADER
SCHEDULER = _sync.ACTOR_SCHEDULER
COLLECTOR = _sync.ACTOR_COLLECTOR


def get_builtin_actor(builtin_key: str) -> AbstractUser:
    """Return the active built-in program actor for `builtin_key`.

    Raises `MissingActor` if it does not exist or is not active — auth sync must
    run before any system-initiated service-layer write. "Active" is the single
    `policy.is_actor_active` definition (is_active AND deactivated_at IS NULL), so
    a built-in carrying a stray `deactivated_at` is treated as absent here exactly
    as `_evaluate` would deny it — never resolved as a usable actor that then fails
    policy (the zombie built-in; doc-auth-per-app-standards "one definition of
    active").
    """
    from tap_auth.policy import is_actor_active

    actor = get_user_model().objects.filter(tap_builtin_key=builtin_key).first()
    if actor is None or not is_actor_active(actor):
        raise MissingActor(
            f"built-in actor {builtin_key!r} not found or inactive — run auth sync "
            "(manage.py sync_auth) before system-initiated work"
        )
    return actor


@contextlib.contextmanager
def acting_as(
    actor: AbstractUser,
    *,
    batch_id: str | None = None,
    batch_name: str | None = None,
    batch_description: str | None = None,
) -> Iterator[None]:
    """Bind `actor` as the active `CallerContext` for the duration of the block.

    The no-request analogue of `CallerContextMiddleware`: where the middleware
    binds `request.user` for a request, this binds an explicitly-resolved actor
    for a no-request unit of work — a Django-Tasks worker body, a scheduler tick,
    the boot sequence — then restores the prior context on exit (so the actor
    never leaks past the block onto a reused worker thread, mirroring the
    middleware's boundary-clearing). Downstream service-layer calls that pass no
    `caller_context` inherit this actor from the contextvar (`write_batch` /
    `grift_import` resolve the ambient actor when none is passed explicitly).

    Generic by construction — parameterized by the *resolved* actor, not a
    builtin key — so every no-request subsystem shares one helper:
    `with acting_as(get_builtin_actor(COLLECTOR)):` (collector runtime),
    `with acting_as(get_builtin_actor(SCHEDULER)):` (scheduler tick),
    `with acting_as(get_builtin_actor(BOOTLOADER)):` (boot), and a future
    `with acting_as(delegated):` for an AI runner acting on a user's behalf
    (req-tap-auth-actor-model; the on-behalf-of delegation is
    req-tap-auth-ai-placeholder).

    Args:
        actor: The resolved, named actor to bind. A program actor for system
            work; never `None` (a no-request path that cannot name its actor is a
            defect — resolve it or fail loudly at `get_builtin_actor`).
        batch_id: An optional existing batch scope to join. When omitted, the
            service layer mints a fresh batch_id per write as usual.
        batch_name: The name a batch minted inside the block carries when the write
            names none itself (req-grid-service-batch-label-required). Ignored by a
            write that joins an existing batch.
        batch_description: The description that goes with `batch_name`.
    """
    prior = get_caller_context()
    set_caller_context(
        CallerContext(user=actor, batch_id=batch_id, batch_name=batch_name, batch_description=batch_description)
    )
    try:
        yield
    finally:
        set_caller_context(prior)
