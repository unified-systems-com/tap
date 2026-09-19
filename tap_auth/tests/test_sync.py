"""Tests for the auth bootstrap sync (req-tap-auth-capabilities, req-tap-auth-builtins)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from tap_auth import sync
from tap_auth.capabilities import ALL_CAPABILITY_NAMES, codename_for
from tap_auth.models import Capability, ProtectedGroup

User = get_user_model()


def _inject_rogue_capability(name: str = "rogue.cap") -> None:
    """Create a Capability + Permission not present in the canonical registry."""
    content_type = ContentType.objects.get_for_model(Capability)
    perm = Permission.objects.create(content_type=content_type, codename=codename_for(name), name="rogue")
    Capability.objects.create(name=name, description="rogue", risk="low", permission=perm)


class TestBuiltinKeySingleSource:
    """The built-in actor/group keys have one code home (derive-same-fact-twice collapse).

    sync.py is the v0 authoritative definition (it writes the actor rows;
    req-tap-auth-builtins); actors.py aliases its constants, and the role keys
    in tap_auth.roles.json are coupled by name. These pins hold until the
    per-app declarative program-users file replaces the wiring
    (req-tap-auth-program-users, deferred).
    """

    def test_actors_module_aliases_sync_constants(self):
        # The resolver's names must BE sync's objects — a reintroduced literal
        # in actors.py would still equal these today, but this pins the intent
        # and fails the moment either side drifts.
        from tap_auth import actors

        assert actors.BOOTLOADER == sync.ACTOR_BOOTLOADER
        assert actors.SCHEDULER == sync.ACTOR_SCHEDULER
        assert actors.COLLECTOR == sync.ACTOR_COLLECTOR

    def test_every_protected_group_key_is_a_role_key(self):
        # The JSON leg: each group's builtin key doubles as its role key in
        # tap_auth.roles.json. _GROUP_BUNDLES resolves through the role registry
        # at import (so a missing key already fails loudly); this makes the
        # coupling an explicit, named pin rather than an import side effect.
        from tap_auth.roles import ROLES

        for key in (
            sync.GROUP_ADMIN,
            sync.GROUP_VIEWER,
            sync.GROUP_BOOTLOADER,
            sync.GROUP_SCHEDULER,
            sync.GROUP_COLLECTOR,
        ):
            assert key in ROLES, f"group key {key!r} has no matching role in tap_auth.roles.json"

    def test_dedicated_actor_key_equals_its_group_key(self):
        # The documented convention: where a role has a single dedicated program
        # actor, group builtin_key == actor tap_builtin_key.
        assert sync.ACTOR_BOOTLOADER == sync.GROUP_BOOTLOADER
        assert sync.ACTOR_SCHEDULER == sync.GROUP_SCHEDULER
        assert sync.ACTOR_COLLECTOR == sync.GROUP_COLLECTOR


@pytest.mark.django_db
class TestSyncCapabilities:
    def test_creates_all_with_permissions(self):
        result = sync.sync_capabilities()
        assert Capability.objects.count() == len(ALL_CAPABILITY_NAMES)
        assert Capability.objects.exclude(permission=None).count() == len(ALL_CAPABILITY_NAMES)
        # created+updated covers the full registry regardless of whether the
        # session-level auth seed already created the rows (conftest).
        assert result["created"] + result["updated"] == len(ALL_CAPABILITY_NAMES)

    def test_idempotent(self):
        sync.sync_capabilities()
        second = sync.sync_capabilities()
        assert Capability.objects.count() == len(ALL_CAPABILITY_NAMES)
        assert second["created"] == 0
        assert second["updated"] == len(ALL_CAPABILITY_NAMES)

    def test_public_name_projects_codename(self):
        sync.sync_capabilities()
        cap = Capability.objects.get(name="grid.read")
        assert cap.permission is not None
        assert cap.permission.codename == "grid_read"

    def test_undeclared_drift_hard_fails(self):
        sync.sync_capabilities()
        _inject_rogue_capability()
        with pytest.raises(sync.AuthSyncError, match="undeclared capability drift"):
            sync.sync_capabilities()

    def test_declared_prune_removes(self):
        sync.sync_capabilities()
        _inject_rogue_capability()
        sync.sync_capabilities(declared_prune=("rogue.cap",))
        assert not Capability.objects.filter(name="rogue.cap").exists()
        assert not Permission.objects.filter(codename="rogue_cap").exists()

    def test_stale_prune_declaration_hard_fails(self):
        sync.sync_capabilities()
        with pytest.raises(sync.AuthSyncError, match="declared-but-not-present"):
            sync.sync_capabilities(declared_prune=("never.existed",))


@pytest.mark.django_db
class TestSyncGroupsAndActors:
    def test_protected_groups_created_with_bundles(self):
        sync.sync_capabilities()
        sync.sync_protected_groups()
        keys = set(ProtectedGroup.objects.values_list("builtin_key", flat=True))
        assert keys == {"tap_admin", "tap_viewer", "tap_bootloader", "tap_cares.scheduler", "tap_cares.collector"}
        assert Group.objects.get(name="tap_admin").permissions.count() == len(ALL_CAPABILITY_NAMES)
        # tap_viewer is the human-only read role: grid.read and nothing else.
        assert set(Group.objects.get(name="tap_viewer").permissions.values_list("codename", flat=True)) == {"grid_read"}
        collector_caps = set(
            Group.objects.get(name="tap_cares.collector").permissions.values_list("codename", flat=True)
        )
        assert collector_caps == {
            "grid_read",
            "grid_write",
            "grid_import_grift",
            "grid_reconcile",
            "cares_run_collectors",
            "cares_self_test_collectors",
        }

    def test_group_bundle_is_hard_synced(self):
        sync.sync_capabilities()
        sync.sync_protected_groups()
        collector = Group.objects.get(name="tap_cares.collector")
        # Inject a stray grant; a re-sync must remove it (set() semantics).
        collector.permissions.add(Permission.objects.get(codename="grid_purge"))
        sync.sync_protected_groups()
        assert not collector.permissions.filter(codename="grid_purge").exists()

    def test_program_actors_created_unusable_password(self):
        sync.sync_auth()
        bootloader = User.objects.get(tap_builtin_key="tap_bootloader")
        assert bootloader.user_kind == "program"
        assert bootloader.is_tap_builtin is True
        assert not bootloader.has_usable_password()
        assert list(bootloader.groups.values_list("name", flat=True)) == ["tap_bootloader"]

    def test_tap_test_created_in_test_mode(self):
        # The suite runs under TAP_TEST_MODE=True (tap.test_settings).
        sync.sync_auth()
        test_actor = User.objects.get(tap_builtin_key="tap_test")
        assert test_actor.user_kind == "program"
        assert "tap_admin" in test_actor.groups.values_list("name", flat=True)

    def test_ensure_test_actor_refuses_outside_test_mode(self, settings):
        settings.TAP_TEST_MODE = False
        with pytest.raises(sync.AuthSyncError, match="TAP_TEST_MODE"):
            sync.ensure_test_actor()

    def test_full_sync_idempotent(self):
        sync.sync_auth()
        sync.sync_auth()
        assert User.objects.filter(tap_builtin_key="tap_bootloader").count() == 1
        # 5 protected groups: tap_admin, tap_viewer (human-membership) + the three
        # program-actor groups (bootloader, scheduler, collector).
        assert ProtectedGroup.objects.count() == 5

    def test_actor_membership_is_authoritative(self):
        """Re-sync removes a stray privileged group from a built-in actor and
        repairs drifted managed fields (hard-sync, not additive — Codex P2)."""
        sync.sync_auth()
        bootloader = User.objects.get(tap_builtin_key="tap_bootloader")
        # Drift: stray tap_admin membership + demoted/deactivated fields.
        bootloader.groups.add(Group.objects.get(name="tap_admin"))
        User.objects.filter(pk=bootloader.pk).update(user_kind="human", is_active=False)

        sync.sync_builtin_actors()

        bootloader.refresh_from_db()
        assert list(bootloader.groups.values_list("name", flat=True)) == ["tap_bootloader"]
        assert bootloader.user_kind == "program"
        assert bootloader.is_active is True

    def test_deactivated_builtin_reactivated_on_sync(self):
        """A built-in carrying deactivated_at is a permanently-denied zombie until
        re-sync clears the whole deactivation trio: `is_actor_active` requires
        is_active AND deactivated_at IS NULL (doc-auth-per-app-standards "one
        definition of active")."""
        from django.utils import timezone

        from tap_auth.actors import get_builtin_actor
        from tap_auth.policy import is_actor_active

        sync.sync_auth()
        bootloader = User.objects.get(tap_builtin_key="tap_bootloader")
        # Zombie drift: deactivated audit fields set while is_active stays True. The
        # pre-fix get_builtin_actor (is_active-only filter) would resolve it, but
        # policy would deny it as inactive.
        User.objects.filter(pk=bootloader.pk).update(deactivated_at=timezone.now(), deactivated_reason="incident")
        bootloader.refresh_from_db()
        assert not is_actor_active(bootloader)

        sync.sync_builtin_actors()

        bootloader.refresh_from_db()
        assert bootloader.deactivated_at is None
        assert bootloader.deactivated_reason == ""
        assert is_actor_active(bootloader)
        # Resolves again as a usable built-in actor (raised MissingActor before).
        assert get_builtin_actor("tap_bootloader").pk == bootloader.pk

    def test_usable_password_on_program_actor_is_repaired(self):
        """A program actor is never a password-login surface — a usable password
        set on one is drift, repaired back to unusable by re-sync (Codex P2)."""
        sync.sync_auth()
        bootloader = User.objects.get(tap_builtin_key="tap_bootloader")
        bootloader.set_password("a-real-password")
        bootloader.save()
        assert bootloader.has_usable_password()

        sync.sync_builtin_actors()

        bootloader.refresh_from_db()
        assert not bootloader.has_usable_password()
