"""tap_auth URL configuration — mounted at ``/auth/`` by ``tap/urls.py``.

tap_auth owns the auth routes (req-tap-auth-app-3): the allauth machinery
(login, logout, social/OIDC login + callback) plus TAP-specific auth surfaces.
allauth's URLConf is included WITHOUT a namespace so its global view names
(``account_login``, ``account_logout``, the openid_connect routes) reverse as
allauth expects. The ``/auth`` prefix is reserved against Page slugs via the
AppConfig ``reserved_url_prefixes`` registry (req-tap-auth-app-4).

Resulting top-level paths (under ``/auth/``):
    /auth/passkey/login/                         native passkey login page (LOGIN_URL)
    /auth/passkey/login/options/                 authentication options (POST)
    /auth/passkey/login/verify/                  assertion verify + session (POST)
    /auth/enroll/<public-id>/                    invitation redemption shell (anon)
    /auth/enroll/<public-id>/options/            registration options (POST)
    /auth/enroll/<public-id>/verify/             redeem + bind + login (POST)
    /auth/login/                                 allauth (federated) login
    /auth/logout/                                allauth logout
    /auth/oidc/<provider_id>/login/              OIDC login initiation
    /auth/oidc/<provider_id>/login/callback/     OIDC callback
    /auth/no-access/                             generic no-access landing

The native passkey + enroll routes sit under ``/auth/`` deliberately: it is a
``TAP_LOGIN_EXEMPT_PREFIXES`` entry, so the anonymous invitee / logging-in user is
never bounced to the login wall (req-tap-auth-passkey-enrollment / webauthn-11).
"""

from __future__ import annotations

from django.urls import include, path, register_converter

from tap_auth import views, views_enroll, views_login


class InvitationPublicIdConverter:
    """URL converter for an invitation's public id: ``secrets.token_hex(8)``.

    Django's default ``<str:>`` converter is ``[^/]+``, which in Python's ``re``
    matches a NEWLINE — so a request for ``/auth/enroll/abc%0A<forged line>/``
    reached the view and the id was logged verbatim, letting an UNAUTHENTICATED
    caller write arbitrary lines into TAP's log stream (CWE-117; SonarCloud
    pythonsecurity:S5145). ``Invitation.public_id``'s own help text calls it "the
    log-safe lookup handle", which was true of the minted value and false of the
    one that arrives off the wire.

    Constraining the route makes that claim true again: a malformed id is a 404
    at resolution time and never reaches a view, a logger, or the database. This
    is the boundary, not a filter at the log call — sanitising 11 log sites
    leaves the 12th to be written later.
    """

    regex = "[0-9a-f]{16}"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value


register_converter(InvitationPublicIdConverter, "invite_id")

urlpatterns = [
    # Native passkey login (the LOGIN_URL target — first-party, no IdP).
    path("passkey/login/", views_login.login_page, name="passkey_login"),
    path("passkey/login/options/", views_login.login_options, name="passkey_login_options"),
    path("passkey/login/verify/", views_login.login_verify, name="passkey_login_verify"),
    # Anonymous invitation redemption (secret rides the URL fragment).
    path("enroll/<invite_id:public_id>/", views_enroll.enroll_page, name="passkey_enroll"),
    path("enroll/<invite_id:public_id>/options/", views_enroll.enroll_options, name="passkey_enroll_options"),
    path("enroll/<invite_id:public_id>/verify/", views_enroll.enroll_verify, name="passkey_enroll_verify"),
    path("no-access/", views.no_access, name="no_access"),
    path("", include("allauth.urls")),
]
