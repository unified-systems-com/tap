"""Native passkey login — the IdP-free front door (req-tap-auth-passkey-rollout-2).

A zero-provider TAP instance has no federated login and (in passwordless mode) no
password login, so it needs a first-party authentication view. This is it:

    GET  /auth/passkey/login/          → login page ("Sign in with a passkey")
    POST /auth/passkey/login/options/  → usernameless authentication options
    POST /auth/passkey/login/verify/   → verify assertion + establish session

The ceremony is usernameless / discoverable: the user is unknown until the assertion
verifies (req-tap-auth-passkey-webauthn-9/-10). On success we finalize with
``auth.login`` under the :class:`PasskeyBackend`, cycling the session key. The page is
under ``/auth/`` so the login wall never gates it (that would loop).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from tap_auth.http import read_json
from tap_auth.passkey import ceremony, challenge, config

logger = logging.getLogger(__name__)

_PASSKEY_BACKEND = "tap_auth.auth_backends.PasskeyBackend"
_CHALLENGE_KIND = "auth"


@require_GET
@ensure_csrf_cookie
def login_page(request: HttpRequest) -> HttpResponse:
    """Render the native passkey login page (LOGIN_URL target).

    ``local_password_enabled`` decides whether the page offers the password fallback
    (req-tap-auth-passkey-rollout-5). It mirrors ``TAP_LOCAL_PASSWORD_ENABLED`` exactly,
    so the link's visibility tracks the capability: ``TapModelBackend`` refuses password
    auth everywhere when the flag is False, and a link to a path that refuses is worse
    than no link. The fallback is allauth's already-mounted, already-rate-limited login
    view rather than a native one — see the requirement for why serving our own would
    mean rebuilding brute-force protection.

    ``canonical_login_url`` is set exactly when this request arrived on an origin the
    passkey ceremony will refuse (req-tap-auth-passkey-rollout-6). The ceremony origin
    is pinned EXACTLY (scheme+host+port, req-tap-auth-passkey-webauthn-7), and dev
    sessions are also reachable at the labeled ``<name>.tap.localhost`` alias — where
    the browser rejects RP-ID ``localhost`` before any prompt appears. Detecting the
    mismatch server-side lets the page say "sign in over there" BEFORE the click,
    instead of a dead button and a post-hoc SecurityError message.
    """
    return render(
        request,
        "tap_web/auth/passkey_login.html",
        {
            "next": _safe_next(request),
            "local_password_enabled": settings.TAP_LOCAL_PASSWORD_ENABLED,
            "canonical_login_url": _canonical_login_url(request),
        },
    )


def _canonical_login_url(request: HttpRequest) -> str | None:
    """The same login URL on the pinned ceremony origin, or None if already there.

    Comparison is exact-origin (scheme+host+port), mirroring the server-side assertion
    check — if verify would reject this origin, the page should say so up front. When
    ``TAP_PASSKEY_ORIGIN`` is unset the page renders no signpost and the ceremony
    endpoints raise their own configuration error; a misconfigured instance must not
    500 the login page itself.
    """
    try:
        origins = config.expected_origins()
    except ImproperlyConfigured:
        return None
    request_origin = f"{request.scheme}://{request.get_host()}"
    if request_origin in origins:
        return None
    return origins[0].rstrip("/") + request.get_full_path()


@require_POST
def login_options(request: HttpRequest) -> HttpResponse:
    """Return usernameless (discoverable) authentication options + stash the challenge."""
    options_json, challenge_bytes = ceremony.authentication_options()
    challenge.stash(request.session, _CHALLENGE_KIND, challenge_bytes)
    logger.info("[f985] passkey login options issued")
    return HttpResponse(options_json, content_type="application/json")


@require_POST
def login_verify(request: HttpRequest) -> HttpResponse:
    """Verify the assertion and establish an authenticated session (key cycled)."""
    body = read_json(request)
    credential = body.get("credential")
    if not isinstance(credential, dict):
        return JsonResponse({"error": "invalid assertion"}, status=400)

    stashed = challenge.pop(request.session, _CHALLENGE_KIND)
    if stashed is None:
        logger.warning("[173c] passkey login without a live challenge")
        return JsonResponse({"error": "authentication failed"}, status=400)
    expected_challenge, _bound = stashed

    try:
        user = ceremony.authenticate(credential, expected_challenge)
    except ceremony.PasskeyCeremonyError:
        # One generic client-facing failure — clone / forgery / UV-absent / unknown
        # credential are already discriminated in the audit log, never to the client.
        return JsonResponse({"error": "authentication failed"}, status=400)

    auth_login(request, user, backend=_PASSKEY_BACKEND)
    redirect_to = str(body.get("next") or "") or _safe_next(request)
    if not url_has_allowed_host_and_scheme(redirect_to, allowed_hosts={request.get_host()}):
        redirect_to = "/"
    logger.info("[160c] passkey login ok user=%s", user.pk)
    return JsonResponse({"redirect": redirect_to})


def _safe_next(request: HttpRequest) -> str:
    candidate = request.GET.get("next", "")
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return "/"
