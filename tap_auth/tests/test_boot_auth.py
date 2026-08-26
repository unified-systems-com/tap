"""Auth boot section tests (increment 4 — req-tap-auth-boot).

Covers the settings-time readers, fragment validation, provider self-test
gating, the deploy-posture gate, and the last-admin invariant. Also asserts the
shipped operator_sso profile's auth section is valid against the fragment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from tap.secret_naming import SECRET_SUFFIX
from tap_auth.boot import (
    AuthBootError,
    apply_auth_boot_section,
    initial_admins_for_settings,
    providers_for_settings,
    read_auth_section,
    validate_auth_section,
)
from tap_auth.models import UserKind

_NOOP = lambda _msg: None  # noqa: E731


def _section(**over) -> dict:
    s = {
        "description": "test auth section",
        "providers": [],
        "initial_admins": [],
    }
    s.update(over)
    return s


def _provider(**over) -> dict:
    p = {
        "id": "example-google",
        "type": "google_oidc",
        "display_name": "example.com",
        "description": "test provider",
        "allowed_domains": ["example.com"],
    }
    p.update(over)
    return p


def _write_secret(root: Path, key: str = "example-google") -> None:
    (root / f"{key}{SECRET_SUFFIX}").write_text(
        json.dumps(
            {
                "scope": "auth",
                "key": key,
                "kind": "oidc_client",
                "description": "t",
                "data": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "GOCSPX-x"},
            }
        )
    )


# --------------------------------------------------------------------------- #
# settings-time readers (against the shipped operator_sso profile)
# --------------------------------------------------------------------------- #


class TestSettingsReaders:
    def test_read_operator_sso_profile(self):
        section = read_auth_section("operator_sso")
        assert section["providers"][0]["id"] == "example-google"
        assert "operator@example.com" in section["initial_admins"]

    def test_providers_for_settings(self):
        assert providers_for_settings("operator_sso")[0]["type"] == "google_oidc"

    def test_initial_admins_for_settings(self):
        assert initial_admins_for_settings("operator_sso") == ["operator@example.com"]

    def test_missing_profile_is_empty(self):
        assert read_auth_section("does-not-exist") == {}
        assert providers_for_settings("") == []


# --------------------------------------------------------------------------- #
# fragment validation
# --------------------------------------------------------------------------- #


class TestValidation:
    def test_valid_section_passes(self):
        validate_auth_section(_section(providers=[_provider()]))

    def test_missing_description_fails(self):
        with pytest.raises(AuthBootError):
            validate_auth_section({"providers": []})

    def test_unknown_provider_type_fails(self):
        with pytest.raises(AuthBootError):
            validate_auth_section(_section(providers=[_provider(type="saml")]))

    def test_provider_missing_required_fails(self):
        bad = {"id": "p", "type": "google_oidc"}  # no display_name/description
        with pytest.raises(AuthBootError):
            validate_auth_section(_section(providers=[bad]))

    def test_shipped_operator_sso_profile_is_valid(self):
        section = read_auth_section("operator_sso")
        validate_auth_section(section)  # must not raise


# --------------------------------------------------------------------------- #
# apply: provider self-tests + last-admin invariant + deploy gate
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestApply:
    def _make_admin(self, *, active=True, human=True):
        group, _ = Group.objects.get_or_create(name="tap_admin")
        u = get_user_model().objects.create_user(
            username="admin-x",
            is_active=active,
            user_kind=UserKind.HUMAN if human else UserKind.PROGRAM,
        )
        u.groups.add(group)
        return u

    def test_apply_with_provider_passes_offline(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://x"
        _write_secret(tmp_path)
        self._make_admin()
        # deploy=False → offline self-tests only; valid provider + secret + admin
        apply_auth_boot_section(_section(providers=[_provider()]), deploy=False, echo=_NOOP)

    def test_apply_critical_provider_bad_secret_aborts(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)  # no secret written
        settings.TAP_BASE_URL = "https://x"
        self._make_admin()
        with pytest.raises(AuthBootError):
            apply_auth_boot_section(_section(providers=[_provider(critical_for_boot=True)]), deploy=False, echo=_NOOP)

    def test_last_admin_ok_with_active_human_admin(self):
        self._make_admin()
        apply_auth_boot_section(_section(), deploy=False, echo=_NOOP)

    def test_last_admin_ok_with_declared_initial_admin(self):
        # no admin exists, but initial_admins declares a path → OK
        apply_auth_boot_section(_section(initial_admins=["operator@example.com"]), deploy=False, echo=_NOOP)

    def test_last_admin_fails_with_no_admin_no_path(self):
        with pytest.raises(AuthBootError, match="active human tap_admin"):
            apply_auth_boot_section(_section(), deploy=False, echo=_NOOP)

    def test_last_admin_lockout_breakglass_allows(self):
        apply_auth_boot_section(_section(allow_admin_lockout=True), deploy=False, echo=_NOOP)

    def test_program_admin_does_not_satisfy_invariant(self):
        # an inactive or program admin must NOT count as a human admin
        self._make_admin(human=False)
        with pytest.raises(AuthBootError):
            apply_auth_boot_section(_section(), deploy=False, echo=_NOOP)

    def test_deploy_posture_gate_blocks_dev_secret(self, settings):
        # deploy=True with the dev SECRET_KEY/DEBUG posture → abort before providers
        settings.DEBUG = True
        with pytest.raises(AuthBootError, match="deploy security posture"):
            apply_auth_boot_section(_section(initial_admins=["x@y.com"]), deploy=True, echo=_NOOP)
