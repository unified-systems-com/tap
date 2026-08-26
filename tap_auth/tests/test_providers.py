"""Provider framework tests (increment 2 — req-tap-auth-providers,
req-tap-auth-google-oidc).

Covers the cred-independent layers of the OIDC test strategy:
  - layer 1 (config/secret/decision shape) — pure, no network;
  - the live discovery check with a MOCKED issuer (no real Google).
Real-Google end-to-end is the manual smoke; the full callback flow against a
mock issuer lands in increment 3's mockoidc test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import requests

from tap.secret_naming import SECRET_SUFFIX
from tap_auth.providers import (
    ProviderConfig,
    SelfTestPhase,
    SelfTestStatus,
    build_socialaccount_providers,
    get_provider,
    provider_types,
)
from tap_auth.providers.base import ProviderError
from tap_auth.providers.google_oidc import GoogleOidcProvider
from tap_auth.providers.registry import UnknownProviderType
from tap_auth.providers.secrets import resolve_oidc_client_secret, secret_exists

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _write_secret(
    root: Path,
    key: str,
    *,
    scope: str = "auth",
    client_id: str = "cid.apps.googleusercontent.com",
    client_secret: str = "GOCSPX-abc123",
    **overrides,
) -> Path:
    doc = {
        "scope": scope,
        "key": key,
        "kind": "oidc_client",
        "description": "test oidc client",
        "data": {"client_id": client_id, "client_secret": client_secret},
    }
    doc.update(overrides)
    path = root / f"{key}{SECRET_SUFFIX}"
    path.write_text(json.dumps(doc))
    return path


def _cfg(**over) -> ProviderConfig:
    raw = {
        "id": "example-google",
        "type": "google_oidc",
        "display_name": "example.com (Google)",
        "allowed_domains": ["example.com"],
    }
    raw.update(over)
    return ProviderConfig.from_dict(raw)


def _discovery_doc() -> dict:
    return {
        "issuer": "https://accounts.google.com",
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    }


def _mock_response(status: int, payload: dict | None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    return resp


# --------------------------------------------------------------------------- #
# ProviderConfig + registry
# --------------------------------------------------------------------------- #


class TestProviderConfig:
    def test_from_dict_minimal(self):
        c = ProviderConfig.from_dict(
            {"id": "p", "type": "google_oidc", "display_name": "P", "allowed_domains": ["x.com"]}
        )
        assert c.id == "p"
        assert c.secret_key == "p"  # defaults to id
        assert c.config["allowed_domains"] == ["x.com"]
        assert c.critical_for_boot is True

    def test_from_dict_missing_required_raises(self):
        with pytest.raises(ProviderError, match="missing required field"):
            ProviderConfig.from_dict({"type": "google_oidc"})

    def test_explicit_secret_key(self):
        c = ProviderConfig.from_dict({"id": "p", "type": "google_oidc", "display_name": "P", "secret": "shared-secret"})
        assert c.secret_key == "shared-secret"


class TestRegistry:
    def test_get_known(self):
        assert get_provider("google_oidc").type == "google_oidc"

    def test_unknown_raises(self):
        with pytest.raises(UnknownProviderType, match="unknown provider type"):
            get_provider("saml")

    def test_provider_types(self):
        assert "google_oidc" in provider_types()


# --------------------------------------------------------------------------- #
# secret resolver
# --------------------------------------------------------------------------- #


class TestSecretResolver:
    def test_resolve_valid(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path, "example-google")
        data = resolve_oidc_client_secret("example-google")
        assert data["client_id"].endswith("apps.googleusercontent.com")
        assert data["client_secret"].startswith("GOCSPX-")

    def test_resolve_in_subdir(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        sub = tmp_path / "auth"
        sub.mkdir()
        _write_secret(sub, "example-google")
        assert resolve_oidc_client_secret("example-google")["client_id"]

    def test_missing_raises(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        with pytest.raises(ProviderError, match="no secret file found"):
            resolve_oidc_client_secret("nope")

    def test_schema_invalid_raises(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        # wrong kind → schema FAIL
        _write_secret(tmp_path, "bad", kind="not_oidc")
        with pytest.raises(ProviderError, match="failed oidc_client schema"):
            resolve_oidc_client_secret("bad")

    def test_secret_exists(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path, "present")
        assert secret_exists("present") is True
        assert secret_exists("absent") is False


# --------------------------------------------------------------------------- #
# google_oidc validate_config
# --------------------------------------------------------------------------- #


class TestGoogleOidcValidate:
    def _by_check(self, results):
        return {r.check: r for r in results}

    def test_valid_config_passes(self, settings):
        settings.TAP_BASE_URL = "https://rampart.example.com"
        results = GoogleOidcProvider().validate_config(_cfg())
        by = self._by_check(results)
        assert by["allowed_domains"].status is SelfTestStatus.PASS
        assert by["tap_base_url"].status is SelfTestStatus.PASS

    def test_missing_allowed_domains_fails(self, settings):
        settings.TAP_BASE_URL = "https://rampart.example.com"
        results = GoogleOidcProvider().validate_config(_cfg(allowed_domains=[]))
        assert self._by_check(results)["allowed_domains"].status is SelfTestStatus.FAIL

    def test_missing_tap_base_url_fails(self, settings):
        settings.TAP_BASE_URL = ""
        results = GoogleOidcProvider().validate_config(_cfg())
        assert self._by_check(results)["tap_base_url"].status is SelfTestStatus.FAIL

    def test_wrong_type_fails_fast(self, settings):
        settings.TAP_BASE_URL = "https://x"
        results = GoogleOidcProvider().validate_config(_cfg(type="saml"))
        assert results[0].check == "type" and results[0].status is SelfTestStatus.FAIL

    def test_malformed_allowed_emails_warn(self, settings):
        settings.TAP_BASE_URL = "https://x"
        results = GoogleOidcProvider().validate_config(_cfg(allowed_emails=["not-an-email"]))
        assert self._by_check(results)["allowed_emails"].status is SelfTestStatus.WARN

    def test_callback_url_derivation(self, settings):
        settings.TAP_BASE_URL = "https://rampart.example.com/"
        url = GoogleOidcProvider().callback_url(_cfg())
        assert url == "https://rampart.example.com/auth/oidc/example-google/login/callback/"


# --------------------------------------------------------------------------- #
# google_oidc self_test (offline + mocked live)
# --------------------------------------------------------------------------- #


class TestGoogleOidcSelfTest:
    def _by_check(self, results):
        return {r.check: r for r in results}

    def test_offline_secret_present(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://x"
        _write_secret(tmp_path, "example-google")
        provider = GoogleOidcProvider()
        cfg = _cfg()
        secrets = provider.resolve_secrets(cfg)
        by = self._by_check(provider.self_test(cfg, secrets, live=False))
        assert by["secret"].status is SelfTestStatus.PASS
        assert by["discovery"].status is SelfTestStatus.SKIP
        assert by["discovery"].phase is SelfTestPhase.LIVE

    def test_offline_secret_missing(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://x"
        by = self._by_check(GoogleOidcProvider().self_test(_cfg(), {}, live=False))
        assert by["secret"].status is SelfTestStatus.FAIL

    def test_live_discovery_pass(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://x"
        _write_secret(tmp_path, "example-google")
        provider = GoogleOidcProvider()
        cfg = _cfg()
        with mock.patch.object(requests, "get", return_value=_mock_response(200, _discovery_doc())):
            by = self._by_check(provider.self_test(cfg, provider.resolve_secrets(cfg), live=True))
        assert by["discovery"].status is SelfTestStatus.PASS

    def test_live_discovery_unreachable_fails(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://x"
        _write_secret(tmp_path, "example-google")
        provider = GoogleOidcProvider()
        cfg = _cfg()
        with mock.patch.object(requests, "get", side_effect=requests.ConnectionError("boom")):
            by = self._by_check(provider.self_test(cfg, provider.resolve_secrets(cfg), live=True))
        assert by["discovery"].status is SelfTestStatus.FAIL

    def test_live_discovery_missing_keys_fails(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        settings.TAP_BASE_URL = "https://x"
        _write_secret(tmp_path, "example-google")
        provider = GoogleOidcProvider()
        cfg = _cfg()
        with mock.patch.object(requests, "get", return_value=_mock_response(200, {"issuer": "x"})):
            by = self._by_check(provider.self_test(cfg, provider.resolve_secrets(cfg), live=True))
        assert by["discovery"].status is SelfTestStatus.FAIL


# --------------------------------------------------------------------------- #
# build_allauth_settings / wiring
# --------------------------------------------------------------------------- #


class TestAllauthWiring:
    def test_build_allauth_settings_entry(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path, "example-google")
        provider = GoogleOidcProvider()
        cfg = _cfg()
        entry = provider.build_allauth_settings(cfg, provider.resolve_secrets(cfg))
        assert entry["provider_id"] == "example-google"
        assert entry["client_id"].endswith("apps.googleusercontent.com")
        assert entry["settings"]["server_url"] == "https://accounts.google.com"

    def test_build_socialaccount_providers_empty(self):
        assert build_socialaccount_providers([]) == {}

    def test_build_socialaccount_providers_one(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path, "example-google")
        raw = {
            "id": "example-google",
            "type": "google_oidc",
            "display_name": "example.com",
            "allowed_domains": ["example.com"],
        }
        out = build_socialaccount_providers([raw])
        assert "openid_connect" in out
        assert out["openid_connect"]["APPS"][0]["provider_id"] == "example-google"

    def test_critical_missing_secret_raises(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)  # no secret written
        raw = {"id": "p", "type": "google_oidc", "display_name": "P", "allowed_domains": ["x.com"]}
        with pytest.raises(ProviderError):
            build_socialaccount_providers([raw])

    def test_noncritical_missing_secret_skipped(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)  # no secret written
        raw = {
            "id": "p",
            "type": "google_oidc",
            "display_name": "P",
            "critical_for_boot": False,
            "allowed_domains": ["x.com"],
        }
        assert build_socialaccount_providers([raw]) == {}

    def test_unknown_type_raises(self):
        with pytest.raises(UnknownProviderType):
            build_socialaccount_providers([{"id": "p", "type": "saml", "display_name": "P"}])
