"""Tests for the tap_auth providers health probe (tap_auth/health.py).

req-tap-auth-providers, req-tap-cares-secrets-conditional-validation. Drives the
probe directly over synthetic provider configs + a tmp secrets root, asserting
the conditional-necessity behavior: no providers is healthy, a configured
provider with a present+valid secret is healthy, and a missing/unknown provider
secret degrades (probe `unhealthy`, overall non-blocking via critical=False).
"""

from __future__ import annotations

import json
from pathlib import Path

from tap.secret_naming import SECRET_SUFFIX
from tap_auth.health import probe_auth_providers
from tap_health.results import ProbeStatus


def _write_secret(root: Path, key: str, *, scope: str = "auth") -> None:
    doc = {
        "scope": scope,
        "key": key,
        "kind": "oidc_client",
        "description": "test oidc client",
        "data": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "GOCSPX-abc123"},
    }
    (root / f"{key}{SECRET_SUFFIX}").write_text(json.dumps(doc), encoding="utf-8")


def _provider(**over: object) -> dict:
    raw: dict = {
        "id": "example-google",
        "type": "google_oidc",
        "display_name": "example.com (Google)",
        "allowed_domains": ["example.com"],
    }
    raw.update(over)
    return raw


class TestProbeAuthProviders:
    def test_no_providers_is_healthy(self, settings) -> None:
        settings.TAP_AUTH_PROVIDERS = []
        result = probe_auth_providers()
        assert result.status is ProbeStatus.HEALTHY

    def test_valid_provider_with_secret_is_healthy(self, tmp_path, settings) -> None:
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://tap.example.com"
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        _write_secret(tmp_path, "example-google")
        result = probe_auth_providers()
        assert result.status is ProbeStatus.HEALTHY

    def test_missing_secret_degrades(self, tmp_path, settings) -> None:
        settings.TAP_SECRETS_ROOT = str(tmp_path)  # empty — no secret file
        settings.TAP_BASE_URL = "https://tap.example.com"
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        result = probe_auth_providers()
        assert result.status is ProbeStatus.UNHEALTHY
        assert result.code == "auth.providers.selftest_failed"
        assert any("example-google:secret" == f for f in result.context["failed"])

    def test_unknown_provider_type_fails(self, tmp_path, settings) -> None:
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_AUTH_PROVIDERS = [_provider(type="saml")]
        result = probe_auth_providers()
        assert result.status is ProbeStatus.UNHEALTHY
        assert "example-google:unknown_type" in result.context["failed"]

    def test_malformed_config_reports_config_error(self, settings) -> None:
        settings.TAP_AUTH_PROVIDERS = [{"type": "google_oidc"}]  # missing id/display_name
        result = probe_auth_providers()
        assert result.status is ProbeStatus.UNHEALTHY
        assert result.code == "auth.providers.config_error"


class TestProbeRegistration:
    def test_probe_is_registered(self) -> None:
        from tap_health.registry import health_probe_registry

        probe = health_probe_registry.get("auth.providers")
        assert probe.group == "tap_auth"
        assert probe.critical is False
