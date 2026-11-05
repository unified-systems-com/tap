"""Tests for the on-by-default enforcement primitives (req-tap-auth-policy).

The backstop is stateless (req-tap-auth-policy-8): `assert_write_authorized` /
`assert_read_authorized` re-check what the *actor* holds via `policy.can`, with no
decision ledger. So these tests assert on the actor's capability profile — an
actor that holds the required capability passes; one that lacks it (or is absent)
fails closed with `UnguardedOperation`.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from tap_auth import capabilities as caps
from tap_auth import policy, sync
from tap_auth.enforcement import (
    assert_program_actor,
    assert_read_authorized,
    assert_write_authorized,
    requires_capability,
)
from tap_auth.errors import CapabilityDenied, MissingActor, UnguardedOperation
from tap_auth.models import Capability, User, UserKind
from tap_grid.caller_context import CallerContext

pytestmark = pytest.mark.django_db


@pytest.fixture
def synced():
    sync.sync_auth()


def _admin_ctx() -> CallerContext:
    user = User.objects.create_user(username="alice", password="x")
    user.groups.add(Group.objects.get(name="tap_admin"))
    return CallerContext(user=user)


def _no_caps_ctx() -> CallerContext:
    return CallerContext(user=User.objects.create_user(username="bob", password="x"))


def _ctx_with_caps(*capabilities: str, username: str) -> CallerContext:
    """A context whose actor holds exactly `capabilities` (via one ad-hoc group).

    Lets a test pin a precise capability profile — e.g. holds grid.write but not
    grid.delete — independent of the built-in bundles.
    """
    group = Group.objects.create(name=f"grp-{username}")
    content_type = ContentType.objects.get_for_model(Capability)
    for capability in capabilities:
        group.permissions.add(Permission.objects.get(content_type=content_type, codename=caps.codename_for(capability)))
    user = User.objects.create_user(username=username, password="x")
    user.groups.add(group)
    return CallerContext(user=user)


class TestRequiresCapability:
    def test_allows_authorized_and_backstop_passes_inside(self, synced):
        @requires_capability("grid.write")
        def guarded_write(*, caller_context: CallerContext | None = None) -> str:
            # The actor holds grid.write, so the stateless write backstop passes.
            assert_write_authorized(caller_context)
            return "ok"

        assert guarded_write(caller_context=_admin_ctx()) == "ok"

    def test_denies_unauthorized(self, synced):
        @requires_capability("grid.write")
        def guarded_write(*, caller_context: CallerContext | None = None) -> str:
            return "ok"

        with pytest.raises(CapabilityDenied):
            guarded_write(caller_context=_no_caps_ctx())

    def test_missing_actor(self, synced):
        from tap_grid.caller_context import set_caller_context

        @requires_capability("grid.write")
        def guarded_write(*, caller_context: CallerContext | None = None) -> str:
            return "ok"

        # Clear the ambient actor so there is genuinely no one to inherit — an
        # actor-less call must fail closed (the autouse fixture otherwise binds
        # tap_test, which the decorator would inherit for an explicit user=None).
        set_caller_context(None)
        with pytest.raises(MissingActor):
            guarded_write(caller_context=CallerContext(user=None))

    def test_resolves_from_contextvar(self, synced):
        @requires_capability("grid.read")
        def guarded_read(*, caller_context: CallerContext | None = None) -> str:
            return "ok"

        from tap_grid.caller_context import set_caller_context

        # No explicit caller_context → the decorator resolves the actor from the
        # contextvar and authorizes grid.read against it. (The backstop receiving a
        # resolved actor is the chokepoint's job — write_batch re-resolves ambient
        # before asserting; see TestWriteBackstop for the backstop itself.)
        set_caller_context(_admin_ctx())
        try:
            assert guarded_read() == "ok"
        finally:
            set_caller_context(None)


class TestWriteBackstop:
    def test_actor_holding_write_passes(self, synced):
        assert_write_authorized(_admin_ctx())  # admin holds grid.write → no raise

    def test_unguarded_write_fails_closed(self, synced):
        # An actor that does not hold grid.write reaching the write commit fails
        # closed — the stateless re-check, no ledger.
        with pytest.raises(UnguardedOperation, match="unguarded write"):
            assert_write_authorized(_no_caps_ctx())

    def test_actorless_write_fails_closed(self, synced):
        # The backstop consumes the ctx handed to it directly (no ambient
        # inheritance), so a user=None ctx fails closed regardless of any bound
        # ambient actor.
        with pytest.raises(UnguardedOperation, match="unguarded write"):
            assert_write_authorized(CallerContext(user=None))

    def test_read_only_actor_fails_write_backstop(self, synced):
        ctx = _ctx_with_caps("grid.read", username="reader")
        with pytest.raises(UnguardedOperation, match="unguarded write"):
            assert_write_authorized(ctx)

    def test_write_only_actor_cannot_delete(self, synced):
        """grid.write covers a write op but NOT a delete op — a delete batch
        requires grid.delete specifically (per-op granularity)."""
        ctx = _ctx_with_caps("grid.write", username="writer")
        assert_write_authorized(ctx, needs_write=True, needs_delete=False)  # ok
        with pytest.raises(UnguardedOperation, match="unguarded delete"):
            assert_write_authorized(ctx, needs_write=False, needs_delete=True)

    def test_import_grift_cover_does_not_satisfy_delete(self, synced):
        """The {grid.delete}-only split: a broad cover (grid.import_grift) does NOT
        satisfy the delete backstop — only grid.delete does. A bootloader holds
        import_grift but must not tombstone through it."""
        ctx = _ctx_with_caps("grid.import_grift", "grid.write", username="importer")
        assert_write_authorized(ctx, needs_write=True, needs_delete=False)  # write ok
        with pytest.raises(UnguardedOperation, match="unguarded delete"):
            assert_write_authorized(ctx, needs_write=False, needs_delete=True)

    def test_backstop_reflects_actor_not_prior_authorize(self, synced):
        """No cross-call state: a prior successful authorize() for a privileged
        actor must not make a later backstop pass for a different, unprivileged
        actor — the cross-request leak the removed ledger used to allow."""
        policy.authorize(_admin_ctx(), "grid.write")  # privileged authorize happens
        with pytest.raises(UnguardedOperation, match="unguarded write"):
            assert_write_authorized(_no_caps_ctx())  # different actor, lacks grid.write


class TestReadBackstop:
    def test_actor_holding_read_passes(self, synced):
        assert_read_authorized(_admin_ctx())  # admin holds grid.read → no raise

    def test_unguarded_read_fails_closed(self, synced):
        with pytest.raises(UnguardedOperation, match="unguarded read"):
            assert_read_authorized(_no_caps_ctx())


class TestProgramActorGuard:
    """The INTERNAL_ONLY write bypass is a program-actor-only door: `assert_program_actor`
    passes a program actor and fails closed for a human or no actor (req-tap-auth-actor-model)."""

    def test_allows_program_actor(self):
        prog = User.objects.create_user(username="prog", password="x", user_kind=UserKind.PROGRAM)
        # No raise — a program actor may use the bypass.
        assert assert_program_actor(CallerContext(user=prog), operation="INTERNAL_ONLY write bypass") is None

    def test_refuses_human_actor(self):
        # A human actor (even one that holds grid.write) must never reach the bypass.
        with pytest.raises(UnguardedOperation):
            assert_program_actor(_no_caps_ctx(), operation="INTERNAL_ONLY write bypass")

    def test_refuses_no_actor(self):
        with pytest.raises(UnguardedOperation):
            assert_program_actor(None, operation="INTERNAL_ONLY write bypass")
