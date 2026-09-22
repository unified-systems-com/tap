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
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
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


@pytest.mark.django_db
class TestExceptionDetailStaysInTheLog:
    """CodeQL finding on `PR# 742 - tap`: information exposure through an exception.

    `DeviceFlowError` carries GitHub's raw payload, the endpoint URL and transport
    detail. The caller of these views is UNAUTHENTICATED by necessity — it is a login
    page — so the detail belongs in the log, where the operator is the audience, and the
    response gets a generic failure. The same split `TapSocialAccountAdapter._deny` and
    the closed-route view already use; these views had not adopted it.
    """

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_start_does_not_echo_the_exception_to_the_caller(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        boom = device_flow.DeviceFlowError("https://github.com/login/device/code said {'secret-ish': 'detail'}")
        with mock.patch("tap_auth.device_flow.request_device_code", side_effect=boom):
            resp = views_device.device_start(_request("post", "/auth/device/start/"))
        assert resp.status_code == 502
        assert b"secret-ish" not in resp.content
        assert b"github.com" not in resp.content

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_poll_does_not_echo_the_exception_to_the_caller(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc"}},
        )
        boom = device_flow.DeviceFlowError("https://github.com/login/oauth/access_token blew up: internals")
        with mock.patch("tap_auth.device_flow.poll_once", side_effect=boom):
            resp = views_device.device_poll(request)
        assert resp.status_code == 502
        assert b"internals" not in resp.content
        assert b"github.com" not in resp.content


@pytest.mark.django_db
class TestTheIntervalSurvivesBetweenPolls:
    """`PR# 742 - tap` review finding: `slow_down` was not preserved.

    Each poll is a separate HTTP request. The raised interval was returned to the browser
    and then thrown away, so `poll_once` was called with the module default every time and
    the next pending answer told the client to speed straight back up — earning more
    slow_downs, which is the one thing honouring the interval exists to prevent.
    """

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_start_records_the_interval_github_gave(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        auth = device_flow.DeviceAuthorization(
            device_code="dc", user_code="ABCD-1234", verification_uri="https://github.com/login/device",
            interval=7, expires_in=900,
        )
        request = _request("post", "/auth/device/start/")
        with mock.patch("tap_auth.device_flow.request_device_code", return_value=auth):
            views_device.device_start(request)
        assert request.session["tap_auth.device_flow"]["interval"] == 7

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_a_raised_interval_is_persisted_for_the_next_poll(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc", "interval": 5}},
        )
        with mock.patch("tap_auth.device_flow.poll_once", return_value=device_flow.TokenPending(interval=30)):
            views_device.device_poll(request)
        assert request.session["tap_auth.device_flow"]["interval"] == 30, (
            "the raised interval must outlive the response that reported it"
        )

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_the_stored_interval_is_handed_to_the_next_poll(self, settings):
        """The other half: storing it is useless if the next call does not read it."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc", "interval": 30}},
        )
        with mock.patch(
            "tap_auth.device_flow.poll_once", return_value=device_flow.TokenPending(interval=30)
        ) as poll:
            views_device.device_poll(request)
        assert poll.call_args.kwargs["interval"] == 30

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_a_session_without_an_interval_falls_back_rather_than_failing(self, settings):
        """A flow started before the interval was stored must still complete."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc"}},
        )
        with mock.patch(
            "tap_auth.device_flow.poll_once", return_value=device_flow.TokenPending(interval=5)
        ) as poll:
            resp = views_device.device_poll(request)
        assert resp.status_code == 200
        assert poll.call_args.kwargs["interval"] == device_flow.DEFAULT_INTERVAL


@pytest.mark.django_db
class TestTheSameChokepointAsARedirectLogin:
    """req-tap-auth-github-device-flow-3, proven by the negative test it asks for.

    THIS IS THE TEST THE TRACEABILITY FRAGMENT ALREADY CLAIMED EXISTED. Until now the
    three tests carrying this requirement's marker all asserted the URL SURFACE — that
    the routes are mounted by configuration — and nothing drove a granted token through
    `_complete_login` at all. The requirement is not about routes: it says a policy that
    denies a redirect login must deny a DEVICE login, or the flow is a bypass wearing a
    feature's clothes. A false `Tested` declaration on exactly that requirement is worse
    than an honest gap, because it is the one requirement written to stop this.

    The pipeline below is REAL from `complete_social_login` inward: only the adapter's
    call to GitHub's `/user` is replaced, because that is the network boundary. So
    `pre_social_login` and `evaluate_access` genuinely rule on the identity.
    """

    def _granted_request(self) -> Any:
        request = _request(
            "post",
            "/auth/device/poll/",
            session={"tap_auth.device_flow": {"provider_id": PROVIDER_ID, "device_code": "dc", "interval": 5}},
        )
        request.user = AnonymousUser()
        return request

    @staticmethod
    def _sociallogin_for(user_id: int) -> SocialLogin:
        claims = {"id": user_id, "login": "somebody", "email": "somebody@example.com"}
        account = SocialAccount(provider=PROVIDER_ID, uid=str(user_id), extra_data=claims)
        sl = SocialLogin(account=account)
        sl.user = get_user_model()(username="pending", email="")
        sl.state = {}
        sl.account.pk = None
        sl.email_addresses = []
        return sl

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_a_device_login_by_a_non_allowlisted_account_is_denied(self, settings):
        """The negative test. `_provider()` allowlists 583231; this account is 999999,
        and the device path must refuse it at the same gate a redirect login would."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = self._granted_request()
        granted = device_flow.TokenGranted(access_token="gho_example")
        with (
            mock.patch("tap_auth.device_flow.poll_once", return_value=granted),
            mock.patch(
                "tap_auth.views_device.GitHubOAuth2Adapter.complete_login",
                return_value=self._sociallogin_for(999999),
            ),
        ):
            resp = views_device.device_poll(request)
        assert b'"denied"' in resp.content, "a policy that denies a redirect login must deny a device login"
        assert b"999999" not in resp.content, "the refusal must not tell an anonymous caller which id it saw"

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_the_device_path_does_not_decide_access_itself(self, settings):
        """Structural, and the reason the test above is not enough on its own: a future
        refactor could satisfy it by hand-rolling a check here. The property that matters
        is that this module DELEGATES — the token enters the same `complete_social_login`
        a redirect callback feeds, and something else rules."""
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = self._granted_request()
        granted = device_flow.TokenGranted(access_token="gho_example")
        with (
            mock.patch("tap_auth.device_flow.poll_once", return_value=granted),
            mock.patch(
                "tap_auth.views_device.GitHubOAuth2Adapter.complete_login",
                return_value=self._sociallogin_for(583231),
            ),
            mock.patch("tap_auth.views_device.complete_social_login") as pipeline,
        ):
            views_device.device_poll(request)
        # `assert_called_once()` IS the assertion — it raises on its own. An earlier
        # version wrote `pipeline.assert_called_once(), "…"`, which reads like
        # `assert x, msg` and is actually a two-element tuple evaluated and thrown
        # away (Codacy caught it). The check still fired, but the next person to copy
        # the line into a context where it did not would get a silently vacuous test.
        pipeline.assert_called_once()

    @pytest.mark.spec("req-tap-auth-github-device-flow-3")
    def test_a_permitted_device_login_is_reported_as_success(self, settings):
        """The other side of the denial check, so it cannot pass by denying everything.

        A refusal is detected by asking whether the pipeline AUTHENTICATED anyone, because
        allauth swallows the adapter's `ImmediateHttpResponse` and returns it instead. A
        check written that way has an obvious failure mode — refusing every login — so the
        admit path is pinned here too.
        """
        settings.TAP_AUTH_PROVIDERS = [_provider()]
        request = self._granted_request()
        granted = device_flow.TokenGranted(access_token="gho_example")

        def _authenticate(req, _sociallogin):
            req.user = get_user_model()(username="admitted", email="admitted@example.com")
            req.user.is_active = True
            return None

        with (
            mock.patch("tap_auth.device_flow.poll_once", return_value=granted),
            mock.patch(
                "tap_auth.views_device.GitHubOAuth2Adapter.complete_login",
                return_value=self._sociallogin_for(583231),
            ),
            mock.patch("tap_auth.views_device.complete_social_login", side_effect=_authenticate),
        ):
            resp = views_device.device_poll(request)
        assert b'"ok"' in resp.content

