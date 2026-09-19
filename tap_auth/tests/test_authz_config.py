"""Guard tests for the declarative authz config files (req-tap-auth-capabilities / -roles).

These pin the capability vocabulary and the role bundles loaded from
`tap_auth/tap_auth.capabilities.json` + `tap_auth/tap_auth.roles.json`. They are the compensating
control for the bundles being data rather than typed code: a silent edit that
broadens a security boundary (especially the bootloader's least-privilege set)
fails here. No DB — the registries are loaded at import.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from tap_auth import roles
from tap_auth.capabilities import (
    ALL_CAPABILITY_NAMES,
    CAPABILITIES,
    DELETE_CAPABILITY,
    READ_CAPABILITY,
    WRITE_CAPABILITY,
    get_capability,
)

_TAP_AUTH = Path(__file__).resolve().parent.parent


# --- capabilities (A) ----------------------------------------------------------


def test_capabilities_loaded_and_unique():
    assert CAPABILITIES, "tap_auth.capabilities.json produced an empty registry"
    assert len(ALL_CAPABILITY_NAMES) == len(set(ALL_CAPABILITY_NAMES)), "duplicate capability names"


def test_every_capability_has_a_description():
    for cap in CAPABILITIES:
        assert cap.description.strip(), f"capability {cap.name} has no description"


def test_capabilities_file_has_top_level_description():
    data = json.loads((_TAP_AUTH / "tap_auth.capabilities.json").read_text())
    assert data.get("description", "").strip(), "tap_auth.capabilities.json needs a top-level description"


def test_well_known_capability_constants_are_defined():
    for name in (READ_CAPABILITY, WRITE_CAPABILITY, DELETE_CAPABILITY):
        assert name in ALL_CAPABILITY_NAMES, f"{name} is enforced in code but not defined in tap_auth.capabilities.json"


# --- roles (B) -----------------------------------------------------------------


def test_expected_roles_present():
    assert set(roles.ROLES) == {
        "tap_admin",
        "tap_viewer",
        "tap_bootloader",
        "tap_cares.collector",
        "tap_cares.scheduler",
    }


def test_roles_file_and_each_role_have_descriptions():
    data = json.loads((_TAP_AUTH / "tap_auth.roles.json").read_text())
    assert data.get("description", "").strip(), "tap_auth.roles.json needs a top-level description"
    for key, spec in roles.ROLES.items():
        assert spec.description.strip(), f"role {key} has no description"


def test_every_role_capability_is_defined():
    for key, spec in roles.ROLES.items():
        unknown = [c for c in spec.capabilities if c not in ALL_CAPABILITY_NAMES]
        assert not unknown, f"role {key} names undefined capabilities: {unknown}"


def test_wildcard_is_admin_only_and_grants_everything():
    assert roles.ROLES["tap_admin"].is_wildcard
    assert set(roles.ROLES["tap_admin"].capabilities) == set(ALL_CAPABILITY_NAMES)
    for key, spec in roles.ROLES.items():
        if key != "tap_admin":
            assert not spec.is_wildcard, f"non-admin role {key} must not use the '*' wildcard"


def test_bootloader_role_excludes_destructive_capabilities():
    """The load-bearing least-privilege boundary (req-boot-phases): a boot bug
    must not be able to demolish the grid or delegate."""
    boot = set(roles.role_capabilities("tap_bootloader"))
    for forbidden in ("grid.purge", "grid.delete", "ai.delegate"):
        assert forbidden not in boot, f"tap_bootloader role must exclude {forbidden}"


def test_bootloader_bundle_is_exactly_the_least_privilege_set():
    # Pin the exact set so any change to boot's reach is a deliberate, reviewed edit.
    assert set(roles.role_capabilities("tap_bootloader")) == {
        "grid.read",
        "grid.write",
        "grid.import_grift",
        "grid.admin",
        "auth.manage_users",
        "auth.manage_providers",
        "config.manage",
        "plugins.manage",
        "cares.run_collectors",
        "cares.reconcile_collectors",
    }


def test_cares_bundles_are_least_privilege():
    assert set(roles.role_capabilities("tap_cares.collector")) == {
        "grid.read",
        "grid.write",
        "grid.import_grift",
        "grid.reconcile",
        "cares.run_collectors",
        "cares.self_test_collectors",
    }
    assert set(roles.role_capabilities("tap_cares.scheduler")) == {
        "grid.read",
        "grid.write",
        "cares.run_collectors",
        "cares.run_scheduler",
    }


# --- descriptions flow into the tables (not just the files) --------------------


@pytest.mark.django_db
def test_capability_description_flows_to_table():
    from tap_auth.models import Capability

    cap = Capability.objects.get(name="grid.read")
    assert cap.description == get_capability("grid.read").description
    assert cap.description.strip()
    assert isinstance(cap.description_json, dict)


@pytest.mark.django_db
def test_role_description_flows_to_protected_group():
    from tap_auth.models import ProtectedGroup

    pg = ProtectedGroup.objects.get(builtin_key="tap_bootloader")
    assert pg.description == roles.ROLES["tap_bootloader"].description
    assert pg.description.strip()
    assert isinstance(pg.description_json, dict)


@pytest.mark.django_db
def test_program_actor_description_flows_to_user():
    actor = get_user_model().objects.get(tap_builtin_key="tap_bootloader")
    assert actor.description.strip(), "program actor row should carry its description"
    assert "bootloader" in actor.description.lower()
