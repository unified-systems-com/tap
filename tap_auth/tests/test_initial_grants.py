"""initial_grants + the human/program role-assignment boundary (req-tap-auth-boot,
req-tap-auth-roles).

Covers the declarative role model (every role declares ``assignable_to``), the
login-grant path (email -> human-assignable roles, folding the legacy
``initial_admins`` in), and the load-bearing security edge: a program-only role
can never be granted to a person, and a human-only role can never be bound to a
program actor. The adapter-side application is in test_adapter.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.contrib.auth.models import Group

from tap_auth import boot, roles, sync
from tap_auth.boot import AuthBootError, merge_initial_grants
from tap_auth.capabilities import codename_for
from tap_auth.models import ProtectedGroup

_SCHEMA = Path(roles.__file__).resolve().parent / "schemas" / "auth-boot-section.schema.json"


# --------------------------------------------------------------------------- #
# the declarative role-assignment model
# --------------------------------------------------------------------------- #


class TestRoleAssignmentModel:
    def test_human_assignable_is_admin_and_viewer(self):
        assert roles.HUMAN_ASSIGNABLE_ROLES == frozenset({"tap_admin", "tap_viewer"})

    def test_program_assignable_excludes_viewer_includes_actors(self):
        assert roles.PROGRAM_ASSIGNABLE_ROLES == frozenset(
            {"tap_admin", "tap_bootloader", "tap_cares.collector", "tap_cares.scheduler"}
        )

    def test_admin_is_assignable_to_both(self):
        spec = roles.ROLES["tap_admin"]
        assert spec.grantable_to("human") and spec.grantable_to("program")

    def test_viewer_is_human_only_and_read_only(self):
        spec = roles.ROLES["tap_viewer"]
        assert spec.assignable_to == frozenset({"human"})
        assert spec.capabilities == ("grid.read",)

    def test_program_only_roles_are_not_login_grantable(self):
        for key in ("tap_bootloader", "tap_cares.collector", "tap_cares.scheduler"):
            assert not roles.is_login_grantable(key)

    def test_unknown_role_is_not_login_grantable(self):
        assert not roles.is_login_grantable("tap_wizard")

    def test_every_role_declares_a_principal_class(self):
        for key, spec in roles.ROLES.items():
            assert spec.assignable_to, f"role '{key}' must declare assignable_to"

    def test_schema_grant_enum_stays_in_sync_with_human_assignable(self):
        # Guard: the auth-boot-section initial_grants role enum is the same set the
        # loader derives, so adding/removing a human role can't silently leave the
        # two out of step.
        # Plugin roles are '<slug>.<role>' and validated by shape in the schema, then by
        # membership at boot (req-tap-auth-plugin-declarations); the enum is the core set.
        schema = json.loads(_SCHEMA.read_text())
        core_enum, _plugin_shape = schema["properties"]["initial_grants"]["additionalProperties"]["items"]["anyOf"]
        core_human = {k for k in roles.HUMAN_ASSIGNABLE_ROLES if roles.ROLES[k].declared_by == "tap_auth"}
        assert set(core_enum["enum"]) == core_human


# --------------------------------------------------------------------------- #
# the settings-time merge (initial_grants + initial_admins -> one map)
# --------------------------------------------------------------------------- #


class TestInitialGrantsMerge:
    def test_folds_admins_lowercases_and_unions(self):
        merged = merge_initial_grants(
            {
                "initial_admins": ["Operator@Example.com"],
                "initial_grants": {"operator@example.com": ["tap_viewer"], " Sam@Example.com ": ["tap_viewer"]},
            }
        )
        # grants are applied first, then the folded-in admin — unioned, order-stable.
        assert merged["operator@example.com"] == ["tap_viewer", "tap_admin"]
        assert merged["sam@example.com"] == ["tap_viewer"]

    def test_empty_section_is_empty_map(self):
        assert merge_initial_grants({}) == {}

    def test_malformed_entries_are_skipped(self):
        assert merge_initial_grants({"initial_grants": {"a@b.com": "notalist", "": ["tap_admin"]}}) == {}


# --------------------------------------------------------------------------- #
# boot-phase validation + the last-admin path
# --------------------------------------------------------------------------- #


class TestInitialGrantsBootValidation:
    def test_human_roles_validate(self):
        boot._validate_initial_grants({"initial_grants": {"a@b.com": ["tap_admin", "tap_viewer"]}})

    def test_program_role_aborts_boot(self):
        with pytest.raises(AuthBootError):
            boot._validate_initial_grants({"initial_grants": {"a@b.com": ["tap_bootloader"]}})

    def test_unknown_role_aborts_boot(self):
        with pytest.raises(AuthBootError):
            boot._validate_initial_grants({"initial_grants": {"a@b.com": ["tap_wizard"]}})

    def test_schema_rejects_program_role_in_grants(self):
        # The schema enum is the first gate (before the runtime guard above).
        section = {"description": "t", "initial_grants": {"a@b.com": ["tap_bootloader"]}}
        with pytest.raises(AuthBootError):
            boot.validate_auth_section(section)

    def test_admin_path_declared_via_initial_admins(self):
        assert boot._declares_admin_path({"initial_admins": ["a@b.com"]})

    def test_admin_path_declared_via_grants(self):
        assert boot._declares_admin_path({"initial_grants": {"a@b.com": ["tap_admin"]}})

    def test_viewer_only_grant_does_not_declare_admin_path(self):
        assert not boot._declares_admin_path({"initial_grants": {"a@b.com": ["tap_viewer"]}})


# --------------------------------------------------------------------------- #
# sync: tap_viewer is a protected human group; program binding refuses it
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestViewerGroupSync:
    def test_viewer_group_created_protected_and_read_only(self):
        sync.sync_capabilities()
        sync.sync_protected_groups()
        assert ProtectedGroup.objects.filter(builtin_key="tap_viewer", is_protected=True).exists()
        perms = set(Group.objects.get(name="tap_viewer").permissions.values_list("codename", flat=True))
        assert perms == {codename_for("grid.read")}

    def test_program_actor_refuses_binding_to_human_only_group(self):
        # The complement to the login boundary: a program actor must not be bound
        # to a human-only role (tap_viewer is assignable_to 'human' only).
        with pytest.raises(sync.AuthSyncError):
            sync._ensure_program_actor("tap_test", sync.GROUP_VIEWER)
