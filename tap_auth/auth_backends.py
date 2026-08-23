"""TAP authentication backends (req-tap-auth-local).

``TapModelBackend`` is Django's ``ModelBackend`` with one addition: when
``settings.TAP_LOCAL_PASSWORD_ENABLED`` is False, local password authentication
is refused everywhere — including the Django admin login, which also calls
``authenticate()``. This is how a customer deployment turns off local password
login once IdP login is ready, without:

  * deactivating any user (``is_active`` is untouched), or
  * invalidating any current session (that is a separate, explicit lever —
    ``tap_auth.sessions``).

Disabling local auth must not make the instance unrecoverable: the dependable
recovery floor is out-of-band management-command / shell access (the policy-API
recovery floor), not a live admin login. The allauth social/OIDC backend is
unaffected — external login keeps working.
"""

from __future__ import annotations

from typing import Any

from allauth.account.auth_backends import AuthenticationBackend as AllauthBackend
from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest


def _local_password_enabled() -> bool:
    """Whether local password login is permitted (settings is the single source).

    No defensive default: settings.py always defines this, so a `getattr` fallback
    would be dead code — and its old value (True) pointed the WRONG way for a kill
    switch, meaning an absent setting would have ENABLED password auth. Bare access
    fails closed: if it ever vanished, the login refuses rather than silently opening.
    """
    return bool(settings.TAP_LOCAL_PASSWORD_ENABLED)


class TapModelBackend(ModelBackend):
    """ModelBackend that honors the local-password-enabled toggle."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if not _local_password_enabled():
            # Local password login is disabled; refuse without consulting the DB
            # (fail closed, no user-enumeration timing signal).
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)


class PasskeyBackend(ModelBackend):
    """Backend for phishing-resistant WebAuthn sessions (req-tap-auth-passkey-webauthn-11).

    Passkey login does NOT go through ``authenticate(password=...)``: the ceremony
    (:mod:`tap_auth.passkey.ceremony`) verifies the assertion and resolves the user,
    then the view calls ``django.contrib.auth.login(request, user, backend=...)`` with
    THIS backend passed explicitly, so the session's ``_auth_user_backend`` records
    that the session was minted by a passkey — not by a password path. Borrowing a
    password backend's identity here would mislabel a phishing-resistant session as
    password-auth and corrupt future audit / step-up / password-retirement logic.

    ``authenticate`` always returns ``None`` — this backend never participates in the
    credential-guessing chain; it exists only to (a) be a valid, resolvable ``backend``
    argument to ``auth.login`` and (b) reload the user (``get_user``, inherited) on
    subsequent requests. Permission resolution is inherited from ``ModelBackend`` and
    is identical to the other backends'."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Any:
        return None


class TapAllauthBackend(AllauthBackend):
    """allauth's authentication backend is a SECOND local-password path (it
    authenticates accounts by username/email + password). Gate it with the same
    toggle so disabling local auth closes BOTH paths. Social/OIDC login does not
    go through ``authenticate(password=...)`` (allauth assigns the backend on the
    already-resolved user), so external login is unaffected."""

    def authenticate(self, request: HttpRequest | None, **credentials: Any) -> Any:
        if credentials.get("password") is not None and not _local_password_enabled():
            return None
        return super().authenticate(request, **credentials)
