"""Device-flow login views (req-tap-auth-github-device-flow-3).

The property under test is the one that keeps this from being a bypass: a device login
goes through the SAME policy gate as a redirect login. The negative case is therefore the
important one — a policy that refuses an account must refuse it here too.

The `/auth/device/` routes are under the login-exempt prefix by construction (gating the
login page would loop), so these tests drive them unauthenticated, which is the real
condition.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.test import Client
from django.urls import reverse

from tap_auth import device_flow

PROVIDER_ID = "demo-github"
CLIENT_ID = "Ov23liEXAMPLE"


def _provider(**over: Any) -> dict[str, Any]:
    raw = {
        "id": PROVIDER_ID,
        "type": "github_oauth",
        "display_name": "GitHub",
        "device_flow": True,
        "client_id": CLIENT_ID,
        "allowed_user_ids": [583231],
    }
    raw.update(over)
    return raw


@pytest.mark.django_db
class TestDevicePage:
    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_page_offers_sign_in_when_a_device_provider_is_configured(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        resp = Client().get(reverse("device_login"))
        assert resp.status_code == 200
        assert b"Get my code" in resp.content

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_page_says_so_when_nothing_is_configured(self, settings):
        """An instance with no device provider must not offer a button that cannot work."""
        settings.TAP_AUTH_PROVIDERS = []
        resp = Client().get(reverse("device_login"))
        assert resp.status_code == 503
        assert b"no device-flow provider" in resp.content

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_a_non_device_github_provider_does_not_enable_the_page(self, settings):
        """`device_flow` is a property of a provider ENTRY, not a global mode: an
        ordinary redirect-flow github_oauth provider must not light this up."""
        settings.TAP_AUTH_PROVIDERS = [_provider(device_flow=False)]
        resp = Client().get(reverse("device_login"))
        assert resp.status_code == 503


@pytest.mark.django_db
class TestDeviceStart:
    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_start_returns_the_user_code_and_never_the_device_code(self, settings):
        """The device_code is the bearer of the flow and stays server-side; only the
        user_code — which exists to be read aloud and typed — crosses to the browser."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        auth = device_flow.DeviceAuthorization(
            device_code="SECRET-DEVICE-CODE",
            user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            interval=5,
            expires_in=900,
        )
        client = Client()
        with mock.patch("tap_auth.device_flow.request_device_code", return_value=auth):
            resp = client.post(reverse("device_start"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_code"] == "ABCD-1234"
        assert "SECRET-DEVICE-CODE" not in resp.content.decode()
        assert client.session["tap_auth.device_flow"]["device_code"] == "SECRET-DEVICE-CODE"

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_start_refuses_when_no_provider_is_configured(self, settings):
        settings.TAP_AUTH_PROVIDERS = []
        resp = Client().post(reverse("device_start"))
        assert resp.status_code == 503


@pytest.mark.django_db
class TestDevicePoll:
    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_poll_without_a_started_flow_is_refused(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        resp = Client().post(reverse("device_poll"))
        assert resp.status_code == 400
        assert resp.json()["status"] == "failed"

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_pending_passes_githubs_interval_back_to_the_browser(self, settings):
        """The browser owns the waiting, so it must be told the current interval —
        GitHub can raise it mid-flow and a hardcoded client interval earns slow_downs."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        client = Client()
        session = client.session
        session["tap_auth.device_flow"] = {"provider_id": PROVIDER_ID, "device_code": "dc"}
        session.save()
        with mock.patch("tap_auth.device_flow.poll_once", return_value=device_flow.TokenPending(interval=30)):
            resp = client.post(reverse("device_poll"))
        assert resp.json() == {"status": "pending", "interval": 30}

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_a_terminal_refusal_clears_the_flow(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        client = Client()
        session = client.session
        session["tap_auth.device_flow"] = {"provider_id": PROVIDER_ID, "device_code": "dc"}
        session.save()
        failed = device_flow.TokenFailed(error="expired_token", message="The code expired.")
        with mock.patch("tap_auth.device_flow.poll_once", return_value=failed):
            resp = client.post(reverse("device_poll"))
        assert resp.json()["status"] == "failed"
        assert "tap_auth.device_flow" not in client.session, "an ended flow must not linger in the session"
