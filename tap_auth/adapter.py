"""TAP-owned allauth adapters — the social-login security chokepoint.

allauth's defaults are not safe for TAP's posture: left alone it would
auto-connect a social login to an existing local account by verified email, and
it has no notion of TAP's domain/allowlist policy. This module overrides the
relevant hooks so that EVERY social login is gated by TAP policy before a user
is ever created or connected (req-tap-auth-external-identity,
req-tap-auth-google-oidc):

  - ``pre_social_login`` is the chokepoint. It resolves the provider's access
    policy and runs the provider's ``evaluate_access`` (verified email, ``hd``
    domain, ``allowed_emails``) BEFORE any auto-signup; a disallowed account is
    denied here, never after a user exists. It also enforces linking-disabled:
    a new social account whose verified email matches an existing TAP user is
    refused (no silent auto-connect).
  - ``is_auto_signup_allowed`` gates provisioning on the provider's
    ``auto_provision`` policy.
  - ``save_user`` upserts the ``ExternalIdentity`` (durable ``sub`` link),
    stamps a deterministic non-display username, and applies the declared
    initial-admin grant.

Every denial is a structured security event with a redacted subject, and is
surfaced to the user as a specific, safe hint (login_denied.html) rather than an
opaque failure.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, NoReturn

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpRequest
from django.shortcuts import render
from django.utils import timezone

from tap_auth.errors import DomainNotAllowed
from tap_auth.models import ExternalIdentity, ExternalIdentityStatus, UserKind
from tap_auth.providers import AccessDecision, get_provider, get_provider_config
from tap_auth.roles import is_login_grantable

logger = logging.getLogger(__name__)


def user_display(user: Any) -> str:
    """Human-facing label for a user (allauth ``ACCOUNT_USER_DISPLAY``).

    The generated external username (``ext-<provider>-<hash>``) is a non-display
    login key — the UI must show email/display name instead
    (req-tap-auth-external-identity). Prefer the email; fall back to the username
    only for accounts without one (e.g. a local admin)."""
    email = getattr(user, "email", "") or ""
    return email or user.get_username()


def _redact_subject(subject: str) -> str:
    """Provider subjects (OIDC ``sub``) are never logged in full
    (req-tap-auth-external-identity)."""
    if not subject:
        return "sub#<none>"
    return "sub#" + hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12]


def _pick_claims(extra_data: object) -> dict[str, Any]:
    """Normalize an allauth openid_connect ``extra_data`` into a flat claims dict.

    allauth 65 stores ``extra_data`` WRAPPED as ``{"userinfo": {...},
    "id_token": {...}}`` and only un-wraps it for the uid (``_pick_data``), not
    for ``extract_extra_data``. The security-relevant claims (``email_verified``,
    ``hd``, ``email``, ``sub``) live inside those sub-dicts, so we merge them —
    with the **signed id_token taking precedence** on overlap, honoring the spec's
    "enforce the domain via the returned id_token ``hd`` claim". Falls back to the
    dict itself for non-wrapped/older shapes.
    """
    if not isinstance(extra_data, dict):
        return {}
    userinfo = extra_data.get("userinfo")
    id_token = extra_data.get("id_token")
    if isinstance(userinfo, dict) or isinstance(id_token, dict):
        merged: dict[str, Any] = {}
        if isinstance(userinfo, dict):
            merged.update(userinfo)
        if isinstance(id_token, dict):
            merged.update(id_token)  # signed id_token wins on email_verified / hd / sub
        return merged
    return dict(extra_data)


class TapSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Social-login security chokepoint (see module docstring)."""

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin) -> None:
        provider_id = sociallogin.account.provider
        subject = sociallogin.account.uid
        claims = _pick_claims(sociallogin.account.extra_data)

        config = get_provider_config(provider_id)
        if config is None:
            # A provider with no TAP policy must not be able to log anyone in.
            self._deny(
                request,
                provider_id=provider_id,
                subject=subject,
                decision=AccessDecision(
                    allowed=False,
                    reason=DomainNotAllowed.reason,
                    user_message="This login provider is not configured on this deployment.",
                    log_detail=f"no provider config for '{provider_id}'",
                ),
            )

        decision = get_provider(config.type).evaluate_access(config, claims)
        if not decision.allowed:
            self._deny(request, provider_id=provider_id, subject=subject, decision=decision)

        # Linking disabled (req-tap-auth-external-identity): a NEW social account
        # (not an already-linked returning login) whose verified email already
        # belongs to a TAP user is refused — allauth would otherwise auto-connect.
        if not sociallogin.is_existing and decision.verified_email:
            user_model = get_user_model()
            if user_model.objects.filter(email__iexact=decision.verified_email).exists():
                self._deny(
                    request,
                    provider_id=provider_id,
                    subject=subject,
                    decision=AccessDecision(
                        allowed=False,
                        reason="identity_linking_disabled",
                        user_message=(
                            "An account with this email already exists on this deployment. "
                            "Account linking is disabled; an administrator must resolve this."
                        ),
                        log_detail="new social account; verified email matches an existing user",
                        verified_email=decision.verified_email,
                        hd=decision.hd,
                    ),
                )

    def is_open_for_signup(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        # Social provisioning must NOT be gated by the LOCAL public-signup toggle.
        # allauth's default delegates this to the account adapter's
        # is_open_for_signup (which we close for local self-signup), so without
        # this override a permitted Google login hits "Sign Up Closed". Social
        # signup is governed instead by pre_social_login (security) +
        # is_auto_signup_allowed (per-provider auto_provision).
        return True

    def is_auto_signup_allowed(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        config = get_provider_config(sociallogin.account.provider)
        return bool(config and config.auto_provision)

    def save_user(self, request: HttpRequest, sociallogin: SocialLogin, form: Any = None) -> Any:
        user = super().save_user(request, sociallogin, form)
        self._sync_external_identity(sociallogin, user)
        self._apply_initial_grants(user)
        return user

    # -- internals ---------------------------------------------------------

    def _deny(
        self,
        request: HttpRequest,
        *,
        provider_id: str,
        subject: str,
        decision: AccessDecision,
    ) -> NoReturn:
        """Log a structured security event and short-circuit with a specific,
        safe 403 page. Raises ImmediateHttpResponse — never returns."""
        logger.warning(
            "[4d89] login denied: provider=%s reason=%s subject=%s email=%s detail=%s",
            provider_id,
            decision.reason,
            _redact_subject(subject),
            decision.verified_email or "<none>",
            decision.log_detail,
        )
        response = render(
            request,
            "tap_web/auth/login_denied.html",
            {"reason": decision.reason, "message": decision.user_message},
            status=403,
        )
        raise ImmediateHttpResponse(response)

    def _sync_external_identity(self, sociallogin: SocialLogin, user: Any) -> None:
        provider_id = sociallogin.account.provider
        subject = sociallogin.account.uid
        claims = _pick_claims(sociallogin.account.extra_data)
        config = get_provider_config(provider_id)
        decision = get_provider(config.type).evaluate_access(config, claims) if config else None

        email = (decision.verified_email if decision else "") or claims.get("email") or ""
        display = str(claims.get("name") or "")
        hd = (decision.hd if decision else "") or str(claims.get("hd") or "")
        avatar = str(claims.get("picture") or "")

        ExternalIdentity.objects.update_or_create(
            provider_id=provider_id,
            subject=subject,
            defaults={
                "provider_type": config.type if config else "",
                "user": user,
                "email_snapshot": email,
                "display_name_snapshot": display,
                "hosted_domain_snapshot": hd,
                "last_login": timezone.now(),
                "status": ExternalIdentityStatus.ACTIVE,
            },
        )

        # Deterministic, non-display username + verified email + human kind +
        # display name/avatar (the UI shows these, never the generated username).
        user.username = ExternalIdentity.generate_username(provider_id, subject)
        if email:
            user.email = email
        if claims.get("given_name"):
            user.first_name = str(claims.get("given_name"))
        if claims.get("family_name"):
            user.last_name = str(claims.get("family_name"))
        user.avatar_url = avatar
        user.user_kind = UserKind.HUMAN
        user.save(update_fields=["username", "email", "first_name", "last_name", "avatar_url", "user_kind"])
        logger.info(
            "[0128] external identity synced: provider=%s subject=%s email=%s",
            provider_id,
            _redact_subject(subject),
            email or "<none>",
        )

    def _apply_initial_grants(self, user: Any) -> None:
        """Grant the declared roles for an email on login (req-tap-auth-boot,
        req-tap-auth-roles). Reads the effective ``TAP_AUTH_INITIAL_GRANTS`` map
        (email -> roles; ``initial_admins`` already folded in as ``tap_admin``).

        Add/update-only and idempotent — never removes (a typo or de-listing
        cannot silently revoke; de-provisioning is a separate explicit action).
        Defense-in-depth: even though the boot schema + validation constrain the
        map to human-assignable roles, a role that is not human-assignable (a
        leaked/drifted entry) is refused here too, so a person can never be granted
        a program-actor's authority through this path."""
        if not user.email:
            return
        grants = getattr(settings, "TAP_AUTH_INITIAL_GRANTS", {}) or {}
        roles_for_email = grants.get(user.email.lower())
        if not roles_for_email:
            return
        for role in roles_for_email:
            if not is_login_grantable(role):
                logger.warning(
                    "[6351] refusing non-human-grantable role in initial_grants: email=%s role=%s",
                    user.email,
                    role,
                )
                continue
            group = Group.objects.filter(name=role).first()
            if group is None:
                logger.warning(
                    "[7af2] initial grant declared for %s but group '%s' is missing (run auth sync)",
                    user.email,
                    role,
                )
                continue
            user.groups.add(group)
            logger.info("[c331] initial grant applied: email=%s role=%s", user.email, role)


class TapAccountAdapter(DefaultAccountAdapter):
    """Local-account adapter. Disables public self-signup — local users come
    from boot / createsuperuser, and human users otherwise come only from the
    IdP path (req-tap-auth-local, req-tap-auth-program-users human-introduction
    rule). Local password login itself remains available for dev/recovery."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return False
