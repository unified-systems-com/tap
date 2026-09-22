"""GitHub device-flow token acquisition (req-tap-auth-github-device-flow).

The outcome mapping is the whole risk surface here. Every branch is a decision about
whether to keep polling, stop, or hand back a token — and the expensive mistakes are
`slow_down` treated as terminal (login dies for no reason) and an unrecognised error
treated as pending (a poll loop with no end). Both are pinned below.

No network: GitHub's two endpoints are the boundary, so `requests.post` is mocked and
the assertions are about what THIS module does with GitHub's documented answers.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
import requests

from tap_auth.device_flow import (
    ACCESS_TOKEN_URL,
    DEVICE_CODE_URL,
    VERIFICATION_URI,
    DeviceFlowError,
    TokenFailed,
    TokenGranted,
    TokenPending,
    poll_once,
    request_device_code,
)

CLIENT_ID = "Ov23liEXAMPLE"


def _response(payload: Any, *, status: int = 200) -> mock.Mock:
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


class TestRequestDeviceCode:
    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_no_secret_is_ever_sent(self):
        """The point of the flow: this client is PUBLIC and has no secret to send.

        Asserted on the wire rather than trusted, because a helper that quietly folded
        in a `client_secret` would still work against GitHub and would silently
        reintroduce the distributed-secret problem the flow exists to remove.
        """
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response(
                {"device_code": "dc", "user_code": "ABCD-1234", "interval": 5, "expires_in": 900}
            )
            request_device_code(CLIENT_ID)
        sent = post.call_args.kwargs["data"]
        assert sent["client_id"] == CLIENT_ID
        assert "client_secret" not in sent
        assert post.call_args.args[0] == DEVICE_CODE_URL

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_githubs_verification_uri_wins_over_our_constant(self):
        """Our constant is a fallback, not an assertion about where GitHub wants the
        human sent. If GitHub names a different URI *on GitHub, over https* we use it —
        the allowlist below narrows which values qualify, not whether GitHub's wins."""
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response(
                {
                    "device_code": "dc",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device/somewhere-else",
                    "interval": 7,
                    "expires_in": 600,
                }
            )
            auth = request_device_code(CLIENT_ID)
        assert auth.verification_uri.endswith("somewhere-else")
        assert auth.interval == 7

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_a_malformed_response_fails_loudly(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"user_code": "ABCD-1234"})  # no device_code
            with pytest.raises(DeviceFlowError, match="documented shape"):
                request_device_code(CLIENT_ID)

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_an_empty_client_id_is_refused_before_the_network(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            with pytest.raises(DeviceFlowError, match="client_id"):
                request_device_code("")
        post.assert_not_called()

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_an_unrecognised_client_id_says_so(self):
        """Found by a LIVE probe, not by reading: GitHub answers a bad client_id with
        `{"error": "Not Found"}` — a documented error payload, not a malformed response.
        Before this branch it surfaced as "not the documented shape", which sends the
        reader hunting a parsing bug instead of checking their client_id."""
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "Not Found"})
            with pytest.raises(DeviceFlowError, match="did not recognise this client_id"):
                request_device_code("Ov23liBOGUS")

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_an_unexpected_refusal_is_reported_verbatim(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "some_other_problem", "error_description": "because"})
            with pytest.raises(DeviceFlowError, match="some_other_problem"):
                request_device_code("Ov23liEXAMPLE")

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_a_transport_failure_is_a_device_flow_error(self):
        with mock.patch("tap_auth.device_flow.requests.post", side_effect=requests.RequestException("boom")):
            with pytest.raises(DeviceFlowError, match="could not reach"):
                request_device_code(CLIENT_ID)


class TestPollOnce:
    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_pending_keeps_the_current_interval(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "authorization_pending"})
            outcome = poll_once(CLIENT_ID, "dc", interval=5)
        assert isinstance(outcome, TokenPending) and outcome.interval == 5

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_slow_down_raises_the_interval_and_keeps_polling(self):
        """The expensive mistake in the other direction: `slow_down` is NOT terminal.
        Treating it as failure kills a login that was merely polling too fast."""
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "slow_down"})
            outcome = poll_once(CLIENT_ID, "dc", interval=5)
        assert isinstance(outcome, TokenPending)
        assert outcome.interval == 10, "slow_down must add GitHub's documented 5s penalty"

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_githubs_own_interval_wins_on_slow_down(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "slow_down", "interval": 30})
            outcome = poll_once(CLIENT_ID, "dc", interval=5)
        assert isinstance(outcome, TokenPending) and outcome.interval == 30

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_a_granted_token_comes_back(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"access_token": "gho_example", "token_type": "bearer"})
            outcome = poll_once(CLIENT_ID, "dc")
        assert isinstance(outcome, TokenGranted) and outcome.access_token == "gho_example"

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    @pytest.mark.parametrize("error", ["expired_token", "access_denied", "device_flow_disabled"])
    def test_documented_refusals_are_terminal_and_actionable(self, error: str):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": error})
            outcome = poll_once(CLIENT_ID, "dc")
        assert isinstance(outcome, TokenFailed) and outcome.error == error
        assert outcome.message, "a terminal refusal must say what the operator can do"

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_an_unrecognised_error_is_terminal_not_pending(self):
        """The poll loop must END on a string nobody enumerated. Mapping an unknown
        error to 'pending' is how a login hangs forever against a future GitHub."""
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "something_new", "error_description": "nope"})
            outcome = poll_once(CLIENT_ID, "dc")
        assert isinstance(outcome, TokenFailed)
        assert outcome.error == "something_new"

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_poll_sends_the_device_code_grant_and_no_secret(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response({"error": "authorization_pending"})
            poll_once(CLIENT_ID, "dc-123")
        sent = post.call_args.kwargs["data"]
        assert sent["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
        assert sent["device_code"] == "dc-123"
        assert "client_secret" not in sent
        assert post.call_args.args[0] == ACCESS_TOKEN_URL


class TestTheVerificationUriIsAllowlisted:
    """`PR# 742 - tap` review finding: the verification URI had no allowlist.

    The value comes from GitHub's response, is returned to the browser as JSON, and is
    assigned to an anchor's `href` on a page an unauthenticated visitor is told to click.
    A `javascript:` URI in an href is executed on click — so an attacker-controlled value
    here is script execution on our own origin, not a broken link. The allowlist checks
    scheme AND host, because either alone is bypassable.
    """

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    @pytest.mark.parametrize(
        "hostile",
        [
            "javascript:alert(document.domain)",
            "javascript:alert(1)//github.com",  # host-only check would admit this
            "data:text/html,<script>alert(1)</script>",
            "http://github.com/login/device",  # right host, wrong scheme
            "https://github.com.evil.example/login/device",  # suffix, not the host
            "https://evil.example/login/device",  # scheme-only check would admit this
        ],
    )
    def test_a_uri_that_is_not_https_on_github_is_refused(self, hostile: str):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response(
                {
                    "device_code": "dc",
                    "user_code": "ABCD-1234",
                    "verification_uri": hostile,
                    "interval": 5,
                    "expires_in": 900,
                }
            )
            auth = request_device_code(CLIENT_ID)
        assert auth.verification_uri == VERIFICATION_URI, "a refused URI must fall back, not pass through"

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_a_refused_uri_does_not_kill_the_flow(self):
        """Falling back is the right failure: the constant is where the human needed to
        go anyway, so the login continues and the operator learns from the log."""
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response(
                {
                    "device_code": "dc",
                    "user_code": "ABCD-1234",
                    "verification_uri": "javascript:alert(1)",
                    "interval": 5,
                    "expires_in": 900,
                }
            )
            auth = request_device_code(CLIENT_ID)
        assert auth.user_code == "ABCD-1234"
        assert auth.device_code == "dc"

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_an_absent_uri_falls_back_to_the_constant(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response(
                {"device_code": "dc", "user_code": "ABCD-1234", "interval": 5, "expires_in": 900}
            )
            auth = request_device_code(CLIENT_ID)
        assert auth.verification_uri == VERIFICATION_URI


class TestGitHubsErrorDescriptionStaysInTheLog:
    """`PR# 742 - tap` review finding, missed by the CodeQL fix.

    `DeviceFlowError`'s text was routed to the log and a generic message returned, but
    the unrecognised-error branch of `poll_once` RETURNS rather than raises, so it never
    got the same treatment: GitHub's `error_description` travelled all the way to an
    unauthenticated browser in `TokenFailed.message`.
    """

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_the_description_does_not_reach_the_caller(self):
        with mock.patch("tap_auth.device_flow.requests.post") as post:
            post.return_value = _response(
                {"error": "something_new", "error_description": "app 12345 was suspended by user octocat"}
            )
            outcome = poll_once(CLIENT_ID, "dc")
        assert isinstance(outcome, TokenFailed)
        assert outcome.error == "something_new", "the error CODE is still useful and is not sensitive"
        assert "octocat" not in outcome.message
        assert "12345" not in outcome.message

    @pytest.mark.spec("req-tap-auth-github-device-flow-2")
    def test_the_description_does_reach_the_log(self, caplog):
        """The operator is the audience for the detail — dropping it entirely would trade
        one failure (leaking to a stranger) for another (nobody can diagnose it)."""
        with caplog.at_level("WARNING", logger="tap_auth.device_flow"):
            with mock.patch("tap_auth.device_flow.requests.post") as post:
                post.return_value = _response({"error": "something_new", "error_description": "the real reason"})
                poll_once(CLIENT_ID, "dc")
        assert "the real reason" in caplog.text

