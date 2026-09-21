"""Device-flow login views (req-tap-auth-github-device-flow-3).

Two properties under test. The first is the SURFACE: these routes exist only where a
provider entry declares device flow, so an instance that will never use the flow does not
carry an unauthenticated endpoint that answers 503 forever. The second is the GATE: on a
granted token the device path stops being special and the ordinary pipeline decides
access — a device login that ruled on access itself would be a bypass.

The views are driven with `RequestFactory` rather than `reverse()` on purpose: the routes
are a function of configuration now, so a test that reversed them would be asserting the
URLConf built at import time rather than the behaviour it wants.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.test import RequestFactory

from tap_auth import device_flow, views_device

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


def _request(method: str = "get", path: str = "/auth/device/", session: dict[str, Any] | None = None):
    request = getattr(RequestFactory(), method)(path)
    request.session = session if session is not None else {}
    return request


class TestSurfaceIsConditional:
    """The routes are mounted by configuration, not unconditionally."""

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_no_routes_without_a_device_provider(self, settings):
        """An instance that will never use device flow carries no device endpoint —
        not even one that answers 503. Smallest surface: an unauthenticated route that
        exists only to refuse is surface with no purpose."""
        settings.TAP_AUTH_PROVIDERS = []
        assert views_device.device_urlpatterns() == []

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_no_routes_for_an_ordinary_redirect_provider(self, settings):
        """`device_flow` is a property of a provider ENTRY, not a global mode."""
        settings.TAP_AUTH_PROVIDERS = [_provider(device_flow=False)]
        assert views_device.device_urlpatterns() == []

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_three_routes_when_a_device_provider_is_declared(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        names = {p.name for p in views_device.device_urlpatterns()}
        assert names == {"device_login", "device_start", "device_poll"}


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
        request = _request("post", "/auth/device/start/")
        with mock.patch("tap_auth.device_flow.request_device_code", return_value=auth):
            resp = views_device.device_start(request)
        assert resp.status_code == 200
        assert b"ABCD-1234" in resp.content
        assert b"SECRET-DEVICE-CODE" not in resp.content
        assert request.session["tap_auth.device_flow"]["device_code"] == "SECRET-DEVICE-CODE"

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_start_refuses_without_a_provider_and_never_calls_github(self, settings):
        """Reachable only when mounted, but defence in depth: the view refuses on its
        own rather than trusting the URLConf to have excluded it."""
        settings.TAP_AUTH_PROVIDERS = []
        with mock.patch("tap_auth.device_flow.request_device_code") as start:
            resp = views_device.device_start(_request("post", "/auth/device/start/"))
        assert resp.status_code == 503
        start.assert_not_called()


@pytest.mark.django_db
class TestDevicePoll:
    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_poll_without_a_started_flow_is_refused(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        resp = views_device.device_poll(_request("post", "/auth/device/poll/"))
        assert resp.status_code == 400

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_pending_passes_githubs_interval_back_to_the_browser(self, settings):
        """The browser owns the waiting, so it must be told the CURRENT interval —
        GitHub raises it mid-flow and a hardcoded client interval earns slow_downs."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc"}},
        )
        with mock.patch("tap_auth.device_flow.poll_once", return_value=device_flow.TokenPending(interval=30)):
            resp = views_device.device_poll(request)
        assert b'"interval": 30' in resp.content

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_a_terminal_refusal_clears_the_flow(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc"}},
        )
        failed = device_flow.TokenFailed(error="expired_token", message="The code expired.")
        with mock.patch("tap_auth.device_flow.poll_once", return_value=failed):
            resp = views_device.device_poll(request)
        assert b'"failed"' in resp.content
        assert "tap_auth.device_flow" not in request.session, "an ended flow must not linger in the session"
