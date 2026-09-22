"""GitHub OAuth 2.0 **device flow** — token acquisition for a secretless client.

`req-tap-auth-github-device-flow`. The redirect ("web application") flow cannot serve a
deployment whose hostname is generated per instance: a Codespace forwards its port on a
`*.app.github.dev` host that is unknowable when the OAuth App is registered. Covering it
would mean enabling wildcard callback matching against a GitHub-owned domain shared with
every Codespace user — which GitHub's own documentation advises against — and shipping a
`client_secret` inside a public template repo, where it is not a secret.

The device flow answers both by not having a callback. GitHub's contract (verified
2026-09-21) is:

    POST https://github.com/login/device/code        client_id [+ scope]
    POST https://github.com/login/oauth/access_token client_id + device_code + grant_type

and GitHub states plainly that ``client_secret`` is not needed for it. So this client is
**public**: its whole credential is a `client_id` that may ship in a template.

What this module is NOT
------------------------
It acquires a token and stops. It does not decide who may log in, mint an identity, or
touch ``User``. The access token is handed to allauth's ``GitHubOAuth2Adapter``, which
fetches ``/user`` and ``/user/emails`` and builds a ``SocialLogin``; that goes through
``complete_social_login``, which runs TAP's ordinary pipeline — ``pre_social_login`` →
``evaluate_access`` → ``save_user`` → ``_sync_external_identity`` → grants. A device login
therefore passes the SAME policy chokepoint as a redirect login, keyed on the same numeric
id (``req-tap-auth-github-oauth``). A device path that decided access for itself would be
a bypass wearing a feature's clothes, which is the one thing this module must never become.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

import requests

logger = logging.getLogger(__name__)

DEVICE_CODE_URL: Final = "https://github.com/login/device/code"
ACCESS_TOKEN_URL: Final = "https://github.com/login/oauth/access_token"
VERIFICATION_URI: Final = "https://github.com/login/device"
GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:device_code"

#: What the demo asks for. `read:user` is the least that identifies a person; the verified
#: address rides `user:email`, which `evaluate_access` needs to distinguish a
#: GitHub-asserted address from the self-asserted profile field.
DEFAULT_SCOPE: Final = "read:user user:email"

#: GitHub's floor when it does not say otherwise, and the amount `slow_down` adds.
_DEFAULT_INTERVAL: Final = 5
_SLOW_DOWN_INCREMENT: Final = 5
_TIMEOUT: Final = 10


class DeviceFlowError(RuntimeError):
    """The device flow cannot proceed — a transport failure or a refusal from GitHub."""


@dataclass(frozen=True)
class DeviceAuthorization:
    """GitHub's answer to step 1: what to show the human, and how to poll."""

    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class TokenPending:
    """Not yet authorized. ``interval`` is AUTHORITATIVE — GitHub may raise it."""

    interval: int


@dataclass(frozen=True)
class TokenGranted:
    access_token: str


@dataclass(frozen=True)
class TokenFailed:
    """Terminal: the code expired, the human declined, or the app is misconfigured."""

    error: str
    message: str


TokenOutcomeType = TokenPending | TokenGranted | TokenFailed

#: Terminal errors, mapped to what an operator can act on. `device_flow_disabled` is the
#: one a fresh app hits: device flow is opt-in in the app's settings, so a correct
#: client against an unprepared app fails here and nowhere else.
_TERMINAL: Final[dict[str, str]] = {
    # nosec below: these are USER-FACING MESSAGES keyed by GitHub's error codes. Bandit
    # reads a dict whose key contains "token" as a credential mapping; it is prose.
    "expired_token": "The code expired before it was entered. Start again for a fresh one.",  # nosec B105
    "access_denied": "Authorization was declined on GitHub.",
    "device_flow_disabled": (
        "This GitHub App has not enabled device flow. Enable it in the app's settings "
        "(Settings → Developer settings → the app → Enable Device Flow)."
    ),
    "unsupported_grant_type": "GitHub rejected the device-code grant type.",
    "incorrect_client_credentials": "The configured client_id is not recognised by GitHub.",
    "incorrect_device_code": "GitHub did not recognise this device code.",
}


def request_device_code(client_id: str, *, scope: str = DEFAULT_SCOPE) -> DeviceAuthorization:
    """Step 1: ask GitHub for a device code and the code the human types.

    No secret is sent because none exists — see the module docstring.
    """
    if not client_id:
        raise DeviceFlowError("device flow needs a client_id (it is public; declare it in the boot profile)")
    payload = _post(DEVICE_CODE_URL, {"client_id": client_id, "scope": scope})

    # GitHub answers a bad client_id with an ERROR payload, not a malformed one — verified
    # live 2026-09-21 against a deliberately invalid id, which returned {"error": "Not
    # Found"}. Without this branch that arrives as "not the documented shape", which sends
    # the reader looking for a parsing bug instead of at their client_id.
    if error := str(payload.get("error") or ""):
        detail = str(payload.get("error_description") or "")
        if error in {"Not Found", "invalid_client", "incorrect_client_credentials"}:
            raise DeviceFlowError(
                f"GitHub did not recognise this client_id. Check it, and that the app has "
                f"Device Flow enabled in its settings (GitHub said: {error})"
            )
        raise DeviceFlowError(f"GitHub refused the device-code request: {error}{f' — {detail}' if detail else ''}")

    try:
        return DeviceAuthorization(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            # Honour GitHub's URI rather than the constant: the constant is a fallback,
            # not an assertion about where GitHub wants this human sent.
            verification_uri=str(payload.get("verification_uri") or VERIFICATION_URI),
            interval=int(payload.get("interval") or _DEFAULT_INTERVAL),
            expires_in=int(payload.get("expires_in") or 900),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeviceFlowError(f"GitHub's device-code response was not the documented shape: {payload!r}") from exc


def poll_once(client_id: str, device_code: str, *, interval: int = _DEFAULT_INTERVAL) -> TokenOutcomeType:
    """Step 3, ONE attempt. The caller owns the waiting.

    Deliberately not a blocking loop: a request thread that sleeps for fifteen minutes
    is a worker held hostage by a human who wandered off. The caller polls on its own
    schedule and MUST honour the ``interval`` carried back on ``TokenPending`` — GitHub
    raises it via ``slow_down`` and ignoring that earns more of them.
    """
    payload = _post(ACCESS_TOKEN_URL, {"client_id": client_id, "device_code": device_code, "grant_type": GRANT_TYPE})

    if token := payload.get("access_token"):
        logger.info("[3f1a] device flow: token granted")
        return TokenGranted(access_token=str(token))

    error = str(payload.get("error") or "")
    if error == "authorization_pending":
        return TokenPending(interval=interval)
    if error == "slow_down":
        # GitHub's own interval wins when present; otherwise add its documented penalty.
        raised = int(payload.get("interval") or (interval + _SLOW_DOWN_INCREMENT))
        logger.info("[8c04] device flow: slow_down, polling interval now %ss", raised)
        return TokenPending(interval=raised)
    if error in _TERMINAL:
        logger.warning("[b2e7] device flow refused: error=%s", error)
        return TokenFailed(error=error, message=_TERMINAL[error])

    # An undocumented error is still terminal — better a legible stop than a poll loop
    # that never ends because nobody enumerated this string.
    logger.warning("[5d61] device flow: unrecognised error=%s", error or "<none>")
    return TokenFailed(
        error=error or "unknown",
        message=str(payload.get("error_description") or "GitHub refused the device authorization."),
    )


def _post(url: str, data: dict[str, str]) -> dict[str, Any]:
    """POST form-encoded, ask for JSON, and never let a secret-shaped value reach a log."""
    try:
        resp = requests.post(url, data=data, headers={"Accept": "application/json"}, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise DeviceFlowError(f"could not reach GitHub's device endpoint ({url}): {exc}") from exc
    try:
        payload: dict[str, Any] = resp.json()
    except ValueError as exc:
        raise DeviceFlowError(f"GitHub returned non-JSON from {url} (HTTP {resp.status_code})") from exc
    if not isinstance(payload, dict):
        raise DeviceFlowError(f"GitHub returned a non-object from {url}")
    return payload
