"""Invitation redemption front door — the anonymous enrollment ceremony views.

An invitee opens ``/auth/enroll/<public-id>#<secret>`` (the secret rides the URL
*fragment*, which browsers never send to the server — req-tap-auth-passkey-enrollment-6);
in-page JS reads it and drives a two-step WebAuthn registration:

    GET  /auth/enroll/<public-id>/           → static shell (same for any id)
    POST /auth/enroll/<public-id>/options/   → registration options (gated by secret)
    POST /auth/enroll/<public-id>/verify/    → redeem: create/bind + log in

These live under ``/auth/`` so they inherit ``TAP_LOGIN_EXEMPT_PREFIXES`` — the
invitee is anonymous and must not be bounced to the login wall (Hardening #4). CSRF
stays in force on the POSTs. The GET shell is byte-identical regardless of whether the
public-id resolves; the POST is the single decision point, and it collapses every
failure to one generic message with a constant-time secret compare, so the surface is
non-enumerating.

Redemption finalizes with ``django.contrib.auth.login`` under the ``PasskeyBackend``,
which cycles the session key — the anonymous pre-auth session that held the challenge
and received the secret never becomes the authenticated (often ``tap_admin``) session
(req-tap-auth-passkey-webauthn-11 / Hardening #5).
"""

from __future__ import annotations

import logging
import secrets

from django.contrib.auth import login as auth_login
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from tap_auth import invitations
from tap_auth.http import read_json
from tap_auth.models import InvitationAction, WebAuthnCredential, WebAuthnUserHandle
from tap_auth.passkey import ceremony, challenge

logger = logging.getLogger(__name__)

_PASSKEY_BACKEND = "tap_auth.auth_backends.PasskeyBackend"
_HANDLE_BYTES = 64  # opaque WebAuthn user handle (req-tap-auth-passkey-identity)


def _challenge_kind(public_id: str) -> str:
    """Bind the registration challenge to this specific invitation + session, so a
    challenge minted for one enrollment cannot be replayed against another."""
    return f"reg:{public_id}"


def _harden(response: HttpResponse) -> HttpResponse:
    """No-store / noindex / no-referrer on every enrollment response — the URL carries
    a bearer secret in its fragment; keep it out of caches, indexes, and Referer."""
    response["Cache-Control"] = "no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
@ensure_csrf_cookie
def enroll_page(request: HttpRequest, public_id: str) -> HttpResponse:
    """Static enrollment shell. Identical for every ``public_id`` (no lookup, no
    oracle); the in-page ceremony is the only path that touches the invitation."""
    response = render(request, "tap_web/auth/enroll.html", {"public_id": public_id})
    return _harden(response)


@require_POST
def enroll_options(request: HttpRequest, public_id: str) -> HttpResponse:
    """Return WebAuthn registration options for a valid (secret-gated) invitation.

    Gating the options behind the secret closes the existence oracle a bare
    options endpoint would open. The opaque user handle is minted here and stashed
    WITH the challenge; redeem persists that exact handle onto the created user."""
    secret = _read_secret(request)
    try:
        invitation = invitations.load_redeemable(public_id, secret)
    except invitations.InvitationError:
        return _harden(JsonResponse({"error": invitations.GENERIC_FAILURE}, status=400))

    if invitation.action == InvitationAction.ADD_CREDENTIAL:
        # Additive enrollment for an existing user: reuse their handle so all of a
        # user's credentials share one handle, and exclude already-registered ones.
        # get_or_create, not get: a user who has NEVER registered a passkey has no
        # handle yet — the password-era account adding its first credential (the dev
        # `admin`, and every account that password retirement will migrate). Minting
        # it here persists it before the ceremony; an abandoned ceremony leaves a
        # handle with no credential, which is harmless and reused on the next attempt.
        handle_row, _ = WebAuthnUserHandle.objects.get_or_create(
            # TAP-CRED-BIND: pre-registration-handle — handle only (no key), minted before the ceremony.
            user=invitation.target_user,
            defaults={"handle": secrets.token_bytes(_HANDLE_BYTES).hex()},
        )
        user_handle = bytes.fromhex(handle_row.handle)
        exclude_ids = list(
            WebAuthnCredential.objects.filter(user=invitation.target_user).values_list("credential_id", flat=True)
        )
        user_label = getattr(invitation.target_user, "email", "") or getattr(invitation.target_user, "username", "")
    else:
        user_handle = secrets.token_bytes(_HANDLE_BYTES)
        exclude_ids = []
        user_label = invitation.email or "operator"

    options_json, challenge_bytes = ceremony.registration_options(
        user_handle,
        user_label=user_label,
        display_name=invitation.display_name or user_label,
        exclude_credential_ids=exclude_ids,
    )
    challenge.stash(
        request.session,
        _challenge_kind(public_id),
        challenge_bytes,
        bound={"invite": public_id, "handle": user_handle.hex()},
    )
    logger.info("[0880] enrollment options issued public_id=%s action=%s", public_id, invitation.action)
    return _harden(HttpResponse(options_json, content_type="application/json"))


@require_POST
def enroll_verify(request: HttpRequest, public_id: str) -> HttpResponse:
    """Redeem the invitation: verify the attestation, create/bind the user, log in.

    The secret is read from the POST body and NEVER logged. The stashed challenge +
    handle come from the server-side session (single-use). Redemption itself is
    atomic (:func:`invitations.redeem_invitation`); on success we cycle the session
    key via ``auth.login`` so the authenticated session is brand new."""
    body = read_json(request)
    secret = str(body.get("secret", ""))
    credential = body.get("credential")
    if not isinstance(credential, dict):
        return _harden(JsonResponse({"error": invitations.GENERIC_FAILURE}, status=400))

    stashed = challenge.pop(request.session, _challenge_kind(public_id))
    if stashed is None:
        logger.warning("[63b1] enrollment verify without a live challenge public_id=%s", public_id)
        return _harden(JsonResponse({"error": invitations.GENERIC_FAILURE}, status=400))
    expected_challenge, bound = stashed
    handle_hex = str(bound.get("handle", ""))
    if bound.get("invite") != public_id or not handle_hex:
        logger.warning("[3eea] enrollment challenge binding mismatch public_id=%s", public_id)
        return _harden(JsonResponse({"error": invitations.GENERIC_FAILURE}, status=400))

    try:
        user = invitations.redeem_invitation(
            public_id,
            secret,
            credential=credential,
            expected_challenge=expected_challenge,
            user_handle=bytes.fromhex(handle_hex),
        )
    except invitations.InvitationError:
        # Generic client-facing failure; the specific reason is already logged below
        # the service layer. The consume rolled back, so the invitation stays pending.
        return _harden(JsonResponse({"error": invitations.GENERIC_FAILURE}, status=400))

    # Privilege change: mint the authenticated session from scratch (new key), never
    # reuse the anonymous enroll session (req-tap-auth-passkey-webauthn-11).
    auth_login(request, user, backend=_PASSKEY_BACKEND)
    logger.info("[4dae] enrollment redeemed + logged in public_id=%s user=%s", public_id, user.pk)
    return _harden(JsonResponse({"redirect": "/"}))


def _read_secret(request: HttpRequest) -> str:
    return str(read_json(request).get("secret", ""))
