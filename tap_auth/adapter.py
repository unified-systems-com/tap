"""TAP-owned allauth adapters — the social-login security chokepoint.

allauth's defaults are not safe for TAP's posture: left alone it would
auto-connect a social login to an existing local account by verified email, and
it has no notion of TAP's domain/allowlist policy. This module overrides the
relevant hooks so that EVERY social login is gated by TAP policy before a user
is ever created or connected (req-tap-auth-external-identity,
req-tap-auth-google-oidc):

  - ``pre_social_login`` is the chokepoint. It resolves the provider's access
    policy and runs the provider's ``evaluate_access`` BEFORE any auto-signup; a
    disallowed account is denied here, never after a user exists. The POLICY is the
    provider's (google_oidc: verified email + ``hd`` domain + ``allowed_emails``;
    github_oauth: numeric-id / login / owner allowlist) — this module knows only
    that a decision was made, never a provider's claim vocabulary. It also enforces
    linking-disabled: a new social account whose verified email matches an existing
    TAP user is refused (no silent auto-connect).
  - ``is_auto_signup_allowed`` gates provisioning on the provider's
    ``auto_provision`` policy.
  - ``save_user`` upserts the ``ExternalIdentity`` (durable subject link — an OIDC
    ``sub``, a GitHub numeric user id), stamps a deterministic non-display
    username, and applies the declared initial-admin grant. Display fields come
    from the provider's ``profile_snapshot``; the only email ever written is one
    the IdP itself asserted as verified.

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
from tap_auth.providers.base import VERIFIED_EMAILS_CLAIM, ProfileSnapshot
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
    """Normalize an allauth ``extra_data`` payload into a flat claims dict.

    allauth 65 stores ``extra_data`` WRAPPED as ``{"userinfo": {...},
    "id_token": {...}}`` and only un-wraps it for the uid (``_pick_data``), not
    for ``extract_extra_data``. The security-relevant claims (``email_verified``,
    ``hd``, ``email``, ``sub``) live inside those sub-dicts, so we merge them —
    with the **signed id_token taking precedence** on overlap, honoring the spec's
    "enforce the domain via the returned id_token ``hd`` claim". Falls back to the
    dict itself for non-wrapped/older shapes — which is also the shape a plain
    OAuth2 provider produces (github's ``extra_data`` is the raw ``/user`` body,
    with no ``userinfo``/``id_token`` envelope), so that branch carries both cases.
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


def _claims_for(sociallogin: SocialLogin) -> dict[str, Any]:
    """The claims a provider's ``evaluate_access`` sees for this login.

    ``extra_data`` plus one injected key: ``VERIFIED_EMAILS_CLAIM``, the addresses
    the IdP ITSELF asserts as verified.

    Why the adapter and not each provider: allauth has already resolved this. An
    OIDC id_token carries ``email_verified`` inline, but a plain-OAuth2 provider's
    verification arrives out of band — allauth fetches GitHub's ``/user/emails``,
    turns it into ``SocialLogin.email_addresses``, and then *strips* it back out of
    ``extra_data`` (``GitHubProvider.extract_extra_data``). A provider re-fetching
    it would be a second derivation of a fact allauth already holds; reading it off
    the SocialLogin here is the one derivation.

    Primary-first, verified-only. Unverified addresses are dropped rather than
    ordered last: the point of the list is that every entry on it is trustworthy
    enough to become ``User.email``, which keys the initial-grants role map.
    """
    claims = _pick_claims(sociallogin.account.extra_data)
    addresses = getattr(sociallogin, "email_addresses", None) or []
    verified = [a for a in addresses if getattr(a, "verified", False) and getattr(a, "email", "")]
    verified.sort(key=lambda a: not getattr(a, "primary", False))
    # UNCONDITIONAL for the same reason as the email write above: a conditional
    # assignment leaves an attacker-supplied value in place when the IdP asserted
    # nothing. `extra_data` is upstream-controlled, and a JSON object key may be any
    # string — so a hostile provider CAN mint `tap:verified_emails` in its own payload,
    # despite what the constant's docstring used to claim. Always writing (empty list
    # when nothing is verified) seals the channel (tap#701).
    claims[VERIFIED_EMAILS_CLAIM] = [str(a.email).strip().lower() for a in verified]
    return claims


class TapSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Social-login security chokepoint (see module docstring)."""

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin) -> None:
        provider_id = sociallogin.account.provider
        subject = sociallogin.account.uid
        claims = _claims_for(sociallogin)

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
        self._apply_owner_grant(sociallogin, user)
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
            "[4d89] login denied: provider=%s reason=%s rule=%s subject=%s email=%s detail=%s",
            provider_id,
            decision.reason,
            decision.matched_rule or "<none>",
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
        claims = _claims_for(sociallogin)
        config = get_provider_config(provider_id)
        provider = get_provider(config.type) if config else None
        decision = provider.evaluate_access(config, claims) if (provider and config) else None
        profile = provider.profile_snapshot(config, claims) if (provider and config) else ProfileSnapshot()

        # ONLY a provider-asserted verified email. There used to be an
        # `or claims.get("email")` fallback here, which was unreachable under
        # google_oidc (an allowed decision always carries a verified email) and a
        # privilege-escalation path under any provider whose payload carries an
        # UNVERIFIED address: this value becomes `User.email`, and `User.email` is
        # the key of the TAP_AUTH_INITIAL_GRANTS role map. GitHub's `/user` email
        # is typed in by the account holder, so under github_oauth that fallback
        # would have let anyone who could pass the allowlist... and anyone who
        # could not reach it at all is irrelevant — but an allowlisted account
        # could self-assert an initial-admin's address and be granted tap_admin.
        # No fallback: an unverifiable email is simply absent (req-tap-auth-github-oauth).
        email = (decision.verified_email if decision else "") or ""
        display = profile.display_name
        hd = (decision.hd if decision else "") or profile.hosted_domain
        avatar = profile.avatar_url

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
        # UNCONDITIONAL, and that is the whole point. allauth's
        # `DefaultSocialAccountAdapter.populate_user` — which TAP does NOT override —
        # has ALREADY written the provider's self-asserted email onto this user before
        # we get here. A conditional write leaves that value in place exactly when the
        # provider asserted nothing verified, which is the GitHub case this guard exists
        # for: `/user/emails` can return 404 (allauth's own documented branch), the
        # verified set is then empty, and the self-asserted address would survive into
        # `User.email` — the key of the TAP_AUTH_INITIAL_GRANTS role map (tap#701).
        # An absent assertion must CLEAR the field, never preserve what was there.
        user.email = email
        # Name parts come from the provider's own vocabulary, not from hardcoded
        # Google claim names. A provider that has no given/family split (GitHub has
        # one free-text `name`) leaves these empty rather than guessing a split.
        if profile.first_name:
            user.first_name = profile.first_name
        if profile.last_name:
            user.last_name = profile.last_name
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

    def _apply_owner_grant(self, sociallogin: SocialLogin, user: Any) -> None:
        """Grant the instance OWNER a role, keyed on ``(provider, uid)`` — not on email.

        Why this exists at all. ``_apply_initial_grants`` above keys on ``user.email``, and
        for a Codespace that key is unavailable: ``boot/codespace_demo.boot.json`` says so in
        its own description — ``initial_admins`` / ``initial_grants`` are keyed on a VERIFIED
        EMAIL and nothing can know the visitor's address in advance, because the Codespace
        token is repository-scoped. So the profile declares no grants, the map is empty, and
        the owner lands on ``Forbidden (capability_denied)`` immediately after a completely
        successful sign-in. OBSERVED 2026-09-22 on a live Codespace.

        Why keyed on the id. ``instance_owner()`` already says it for admission: "Only the
        ``user_id`` authorizes. The ``login`` is returned for diagnostics" — an owner known
        by handle cannot be identified after a rename. The identity this instance already
        trusts to ADMIT exactly one person is the identity that should GRANT that person a
        role; introducing email as a second, weaker key for the same decision is how the two
        drift apart. Email is not identity.

        OFF UNLESS ASKED. ``TAP_AUTH_OWNER_ROLE`` is empty by default, so an install that
        does not set it sees no change whatsoever — this cannot retroactively hand anyone a
        role. The Codespaces derivation sets it (``scripts/codespace-env``), which is the one
        deployment where "the account that created this instance" is a meaningful principal.

        Same guarantees as the grant path beside it: add-only, idempotent, never revokes, and
        a role that is not human-grantable is refused here too, so this can never be used to
        give a person a program actor's authority.
        """
        role = (getattr(settings, "TAP_AUTH_OWNER_ROLE", "") or "").strip()
        if not role:
            return

        from tap_auth.providers.github_oauth import instance_owner

        _owner_login, owner_id = instance_owner()
        if not owner_id:
            # No owner resolved. `evaluate_access` already denies in this state; granting on
            # an unresolved owner would be the mirror-image fail-open of that refusal.
            return

        account = getattr(sociallogin, "account", None)
        uid = str(getattr(account, "uid", "") or "").strip()
        if uid != owner_id:
            return

        if not is_login_grantable(role):
            logger.warning("[9d14] refusing non-human-grantable TAP_AUTH_OWNER_ROLE: role=%s", role)
            return

        group = Group.objects.filter(name=role).first()
        if group is None:
            logger.warning(
                "[9d15] owner grant declared for uid=%s but group '%s' is missing (run auth sync)",
                uid,
                role,
            )
            return

        user.groups.add(group)
        logger.info("[9d16] owner grant applied: provider_uid=%s role=%s", uid, role)


class TapAccountAdapter(DefaultAccountAdapter):
    """Local-account adapter. Disables public self-signup — local users come
    from boot / createsuperuser, and human users otherwise come only from the
    IdP path (req-tap-auth-local, req-tap-auth-program-users human-introduction
    rule). Local password login itself remains available for dev/recovery."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return False
