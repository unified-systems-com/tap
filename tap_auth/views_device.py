"""GitHub device-flow login views (req-tap-auth-github-device-flow).

    GET  /auth/device/        → the page: "sign in with GitHub" button
    POST /auth/device/start/  → ask GitHub for a code; show it to the human
    POST /auth/device/poll/   → one poll attempt; on success, complete the login

The page is under ``/auth/`` so the login wall never gates it (that would loop), the
same reason the passkey login page lives there.

**Where the security actually happens: not here.** These views acquire a token and hand
it to allauth's ``GitHubOAuth2Adapter``, which builds a ``SocialLogin``;
``complete_social_login`` then runs TAP's ordinary pipeline — ``pre_social_login`` →
``evaluate_access`` → ``save_user`` → ``_sync_external_identity`` → initial grants. So a
device login is refused by the same policy, on the same numeric-id identity, at the same
chokepoint as a redirect login (``req-tap-auth-github-device-flow-3``). Nothing in this
module decides who may log in, and a change that made it do so would convert the feature
into a bypass.

Polling is driven by the BROWSER, one request at a time, rather than a server-side loop:
a request thread that sleeps until a human finishes typing is a worker held hostage, and
fifteen minutes of them is the whole pool. The interval GitHub returns is authoritative
and is passed back to the client on every pending answer.
"""

from __future__ import annotations

import logging
from typing import Any

from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialApp, SocialToken
from allauth.socialaccount.providers.github.views import GitHubOAuth2Adapter
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from tap_auth import device_flow
from tap_auth.providers import get_provider_config, iter_provider_configs

logger = logging.getLogger(__name__)

#: Where the in-flight device_code lives between the start call and the polls. Session
#: state, not a model: the flow is short-lived (15 minutes), single-browser, and
#: abandoning it should leave nothing behind to clean up.
_SESSION_KEY = "tap_auth.device_flow"


def _device_provider() -> Any:
    """The single configured device-flow provider, or None.

    Device flow is a property of a PROVIDER ENTRY, not a global mode, so an instance
    that has not configured one simply has no device login — the view says so plainly
    rather than offering a button that cannot work.
    """
    for config in iter_provider_configs():
        if config.type == "github_oauth" and bool(config.config.get("device_flow")):
            return config
    return None


def device_urlpatterns() -> list[Any]:
    """The device routes — mounted ONLY when a provider entry declares device flow.

    Not mounted-and-refusing (req-sec-cheap-edges-2, George 2026-09-21). An endpoint
    that exists to answer 503 on every instance that will never use it is surface with no
    purpose: it is reachable unauthenticated (it must be — a login page the wall gates
    would loop), and on an instance where the flow IS enabled the same path makes an
    outbound call to GitHub, so "present but inert" and "present and live" differ only by
    a config value a reader cannot see from the URLConf.

    Reading configuration at URLConf-build time is the established pattern here, not a
    deviation: ``tap_allauth_urlpatterns()`` on the line below does exactly this, and the
    route-inventory guard already derives part of its expected set from the installed
    providers (``_provider_route_names``). The surface is therefore a function of the boot
    profile, which is where an operator can see it.

    The cost, stated plainly: these routes appear at BOOT or not at all. Enabling device
    flow on a running instance requires a restart, and a test that wants them must
    configure a provider before the URLConf is built.
    """
    if _device_provider() is None:
        return []
    return [
        path("device/", device_page, name="device_login"),
        path("device/start/", device_start, name="device_start"),
        path("device/poll/", device_poll, name="device_poll"),
    ]


@require_GET
@ensure_csrf_cookie
def device_page(request: HttpRequest) -> HttpResponse:
    config = _device_provider()
    return render(
        request,
        "tap_web/auth/device_login.html",
        {"configured": config is not None, "display_name": getattr(config, "display_name", "GitHub")},
        status=200 if config is not None else 503,
    )


@require_POST
def device_start(request: HttpRequest) -> JsonResponse:
    """Step 1. Returns what the human needs to see, and nothing else."""
    config = _device_provider()
    if config is None:
        return JsonResponse(
            {"error": "not_configured", "message": "No device-flow provider is configured."}, status=503
        )

    client_id = str(config.config.get("client_id") or "")
    try:
        auth = device_flow.request_device_code(client_id)
    except device_flow.DeviceFlowError as exc:
        # The exception text carries GitHub's raw payload, the endpoint URL and transport
        # detail. The caller here is UNAUTHENTICATED — this is a login page — so it gets a
        # generic failure and the operator gets the whole story in the log. Same split the
        # adapter's `_deny` and the closed-route view already use; CodeQL caught that this
        # view had not adopted it (PR# 742 - tap review).
        logger.warning("[c7a2] device flow could not start: %s", exc)
        return JsonResponse(
            {"error": "start_failed", "message": "Could not start sign-in. See the instance log."}, status=502
        )

    # The device_code is the bearer of this flow — it stays server-side. Only the
    # user_code (which is meant to be read aloud and typed) crosses to the browser.
    request.session[_SESSION_KEY] = {"provider_id": config.id, "device_code": auth.device_code}
    logger.info("[1e6b] device flow started for provider=%s", config.id)
    return JsonResponse(
        {
            "user_code": auth.user_code,
            "verification_uri": auth.verification_uri,
            "interval": auth.interval,
            "expires_in": auth.expires_in,
        }
    )


@require_POST
def device_poll(request: HttpRequest) -> JsonResponse:
    """Step 3, one attempt, then hand off to the ordinary login pipeline."""
    state = request.session.get(_SESSION_KEY) or {}
    device_code = str(state.get("device_code") or "")
    provider_id = str(state.get("provider_id") or "")
    if not device_code:
        return JsonResponse({"status": "failed", "message": "No device login is in progress. Start again."}, status=400)

    config = get_provider_config(provider_id)
    if config is None:
        request.session.pop(_SESSION_KEY, None)
        return JsonResponse({"status": "failed", "message": "That provider is no longer configured."}, status=409)

    client_id = str(config.config.get("client_id") or "")
    try:
        outcome = device_flow.poll_once(client_id, device_code)
    except device_flow.DeviceFlowError as exc:
        # Same reasoning as device_start: detail to the log, not to an anonymous caller.
        logger.warning("[9d33] device flow poll failed: %s", exc)
        return JsonResponse(
            {"status": "failed", "message": "Sign-in could not be completed. See the instance log."}, status=502
        )

    if isinstance(outcome, device_flow.TokenPending):
        return JsonResponse({"status": "pending", "interval": outcome.interval})
    if isinstance(outcome, device_flow.TokenFailed):
        request.session.pop(_SESSION_KEY, None)
        return JsonResponse({"status": "failed", "error": outcome.error, "message": outcome.message})

    # Granted. From here the device path stops being special: the token enters the same
    # adapter a redirect callback would have fed, and the same pipeline decides access.
    request.session.pop(_SESSION_KEY, None)
    return _complete_login(request, provider_id, outcome.access_token)


def _complete_login(request: HttpRequest, provider_id: str, access_token: str) -> JsonResponse:
    """Hand the token to allauth and let TAP's normal gate rule on it.

    ``complete_social_login`` raises ``ImmediateHttpResponse`` when the social adapter
    refuses — which is exactly what ``TapSocialAccountAdapter._deny`` does for a policy
    denial. That is not an error to swallow: it is the gate working, and the caller is
    told the login was refused without being told which clause refused it (the reason is
    in the log, where the operator is the audience).
    """
    from allauth.core.exceptions import ImmediateHttpResponse

    app = SocialApp.objects.filter(provider_id=provider_id).first() or SocialApp(
        provider="github", provider_id=provider_id
    )
    token = SocialToken(app=app, token=access_token)
    adapter = GitHubOAuth2Adapter(request)
    try:
        sociallogin = adapter.complete_login(request, app, token)
        sociallogin.token = token
        complete_social_login(request, sociallogin)
    except ImmediateHttpResponse:
        logger.info("[4b18] device login refused by the access policy (provider=%s)", provider_id)
        return JsonResponse({"status": "denied", "message": "This account is not permitted on this deployment."})
    except Exception:  # noqa: BLE001 - a failed login must not leak a traceback to the browser
        # nosec: the literal is a log MESSAGE that happens to contain the word "token".
        # The token itself is never logged — that is the point of the message.
        logger.exception("[7ff0] device login failed after authorization (provider=%s)", provider_id)  # nosec B105
        return JsonResponse({"status": "failed", "message": "Sign-in failed after authorization."}, status=500)

    logger.info("[2a45] device login completed (provider=%s)", provider_id)
    return JsonResponse({"status": "ok", "redirect": "/"})
