"""Tests for the authorization policy gate (req-tap-auth-policy)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from tap_auth import policy, sync
from tap_auth.errors import (
    CapabilityDenied,
    InactiveActor,
    MissingActor,
    UnknownCapability,
)
from tap_auth.models import User
from tap_grid.caller_context import CallerContext


@pytest.fixture
def synced(db):
    """Auth bootstrap applied: capabilities, groups, built-in actors."""
    sync.sync_auth()


def _admin_user() -> User:
    user = User.objects.create_user(username="alice", password="x")
    user.groups.add(Group.objects.get(name="tap_admin"))
    return user


def _no_caps_user() -> User:
    return User.objects.create_user(username="bob", password="x")


@pytest.mark.django_db
class TestAuthorize:
    def test_admin_allowed(self, synced):
        ctx = CallerContext(user=_admin_user())
        # No raise == allowed (authorize returns None).
        policy.authorize(ctx, "grid.read")
        policy.authorize(ctx, "grid.purge")  # admin holds all

    def test_no_caps_denied(self, synced):
        ctx = CallerContext(user=_no_caps_user())
        with pytest.raises(CapabilityDenied):
            policy.authorize(ctx, "grid.read")

    def test_missing_actor(self, synced):
        with pytest.raises(MissingActor):
            policy.authorize(CallerContext(user=None), "grid.read")

    def test_inactive_actor_denied(self, synced):
        user = _admin_user()
        user.is_active = False
        user.save(update_fields=["is_active"])
        with pytest.raises(InactiveActor):
            policy.authorize(CallerContext(user=user), "grid.read")

    def test_deactivated_actor_denied(self, synced):
        from django.utils import timezone

        user = _admin_user()
        user.deactivated_at = timezone.now()
        user.save(update_fields=["deactivated_at"])
        with pytest.raises(InactiveActor):
            policy.authorize(CallerContext(user=user), "grid.read")

    def test_unknown_capability_fails_closed(self, synced):
        ctx = CallerContext(user=_admin_user())
        with pytest.raises(UnknownCapability):
            policy.authorize(ctx, "bogus.capability")

    def test_superuser_is_not_a_bypass(self, synced):
        """is_superuser must grant nothing at the TAP service boundary."""
        root = User.objects.create_superuser(username="root", password="x")
        assert root.is_superuser is True
        ctx = CallerContext(user=root)
        # No tap_admin membership → denied despite superuser.
        with pytest.raises(CapabilityDenied):
            policy.authorize(ctx, "grid.read")


@pytest.mark.django_db
class TestCanPredicate:
    def test_can_returns_bool(self, synced):
        admin_ctx = CallerContext(user=_admin_user())
        none_ctx = CallerContext(user=_no_caps_user())
        assert policy.can(admin_ctx, "grid.write") is True
        assert policy.can(none_ctx, "grid.write") is False

    def test_can_never_raises(self, synced):
        assert policy.can(CallerContext(user=None), "grid.read") is False
        assert policy.can(CallerContext(user=_admin_user()), "bogus.cap") is False


def _user_in(group_name: str) -> User:
    user = User.objects.create_user(username=f"u-{group_name}", password="x")
    user.groups.add(Group.objects.get(name=group_name))
    return user


# (group, allowed representative cap, forbidden representative cap). One allowed +
# one forbidden per built-in bundle pins the bundle's boundary: a future edit that
# accidentally widens a bundle (e.g. grants the collector `auth.manage_users`, or
# the bootloader `grid.purge`) flips the forbidden assertion red. The forbidden
# caps are chosen to be the dangerous ones each bundle deliberately excludes.
_BUNDLE_MATRIX = [
    # tap_admin holds everything — its "forbidden" slot asserts no real cap is
    # missing by checking the highest-risk one is present (allowed twice).
    ("tap_admin", "grid.purge", None),
    # bootloader: boot powers, but NEVER destructive grid demolition or delegation.
    ("tap_bootloader", "grid.write", "grid.purge"),
    ("tap_bootloader", "config.manage", "grid.delete"),
    ("tap_bootloader", "plugins.manage", "ai.delegate"),
    # collector: read + write/import its batches and delete through a GRIFT `deletes`
    # section (interim, global grant); NEVER user/provider administration or purge.
    ("tap_cares.collector", "grid.import_grift", "auth.manage_users"),
    ("tap_cares.collector", "grid.delete", "grid.purge"),
    # scheduler: bookkeeping writes + trigger collectors; NEVER import or delete.
    ("tap_cares.scheduler", "cares.run_collectors", "grid.import_grift"),
    ("tap_cares.scheduler", "grid.write", "grid.delete"),
]


@pytest.mark.django_db
class TestBundleMatrix:
    """Per-bundle allowed/forbidden capability matrix (catches bundle widening)."""

    @pytest.mark.parametrize(("group", "allowed", "forbidden"), _BUNDLE_MATRIX)
    def test_bundle_boundary(self, synced, group, allowed, forbidden):
        ctx = CallerContext(user=_user_in(group))
        assert policy.can(ctx, allowed) is True, f"{group} should hold {allowed}"
        if forbidden is not None:
            assert policy.can(ctx, forbidden) is False, f"{group} must NOT hold {forbidden}"

    def test_ordinary_user_holds_nothing(self, synced):
        """A user in no group has no capabilities at all — the default-deny floor."""
        ctx = CallerContext(user=_no_caps_user())
        for cap in ("grid.read", "grid.write", "grid.delete", "cares.run_collectors", "auth.manage_users"):
            assert policy.can(ctx, cap) is False
