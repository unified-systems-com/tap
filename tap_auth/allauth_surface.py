"""The allauth URL surface TAP actually serves — enumerated, never inherited.

``path("", include("allauth.urls"))`` mounts whatever the installed django-allauth
version happens to publish. That is an *inherited* authentication surface: it grows
on a dependency bump, and nothing in TAP names, tests or refuses the routes it adds.
The concrete cost (``tap#703``):

    ``/auth/password/set/`` (``account_set_password``) is ``@login_required`` and its
    only other gate is "the user has no usable password". Social signup calls
    ``set_unusable_password()`` on every federated user, so **every federated user
    passes that gate**. A user admitted once by ``evaluate_access`` could mint a local
    password, pair it with a username they can compute themselves
    (``ExternalIdentity.generate_username`` is ``provider_id`` + ``sha256(provider:sub)``),
    and thereafter authenticate locally — a path that never reaches the provider's
    policy gate at all. Every ``allowed_domains`` / ``allowed_emails`` /
    ``allowed_logins`` / ``allowed_user_ids`` / ``owner_only`` clause is routed around,
    permanently, and survives being removed from the allowlist that admitted them.

This module replaces the wholesale include with a **disposition table**: every allauth
route TAP mounts is listed by name with a verdict and a reason. Three states, and the
third one is the point:

    ``SERVE``      — mounted as allauth ships it, for a stated TAP purpose.
    ``CLOSED``     — mounted at the same route, under the same URL *name*, pointing at a
                     refusing view (HTTP 403).
    unclassified   — a route this deployment has never ruled on. Treated as ``CLOSED``
                     and logged. An allauth bump that mounts a new account view is
                     therefore refused on arrival, not served by default; the route
                     inventory test (``tap_auth/tests/test_allauth_url_surface.py``)
                     turns it into a named failure.

**Why closed routes keep their URL name** rather than being dropped from the URLConf:
allauth reverses its own names from places that have nothing to do with the view being
closed. ``allauth/account/middleware.py`` reverses ``account_email`` on *every* request
that 404s under the mount prefix; ``allauth/account/fields.py`` reverses
``account_reset_password`` while rendering the login form; ``internal/templatekit.py``
reverses ``account_signup`` to build the login page's context. Unmounting those names
would raise ``NoReverseMatch`` inside the login page itself — i.e. removing the routes
would break the operator recovery floor this change exists to protect. Refusing the
*request* while keeping the *name* resolvable closes the surface without that coupling,
and is honest besides: the route exists and is deliberately refused (403), which is a
different fact from "no such URL" (404).

**The recovery floor is untouched.** ``local_password_enabled`` (``boot/operator_sso.boot.json``)
is a deliberate operator feature — a floor so a misconfigured OIDC path cannot lock the
operator out. That floor is ``account_login`` plus a password set out-of-band
(``manage.py createsuperuser`` / ``changepassword`` / the bootstrap path in
``tap_auth.sync``), and both remain. What is removed is the *self-service* mint: an
already-authenticated federated principal giving themselves a local credential. An
operator with a usable password could never reach ``account_set_password`` anyway —
allauth redirects them to ``account_change_password`` — so nothing the floor depends on
passes through a closed route.

**The refusal is unconditional.** It does not consult ``TAP_LOCAL_PASSWORD_ENABLED``: a
guard may never be conditional on the value it guards (``tap#700`` rule 2). Leaving local
password login enabled is an operator decision about *who may use an issued credential*;
it was never a decision to let federated users issue themselves one.

See ``req-tap-auth-allauth-surface`` in ``tap_auth/specs/spec-tap-auth-v0.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Final

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import URLPattern, include, path

logger = logging.getLogger(__name__)

SERVE: Final = "serve"
CLOSED: Final = "closed"


@dataclass(frozen=True)
class Disposition:
    """One ruling on one allauth route: served, or refused, and why."""

    verdict: str
    reason: str


#: The verdict for a route no-one has ruled on. Fail closed, and say so.
UNCLASSIFIED: Final = Disposition(
    CLOSED,
    "unclassified — this route is not in TAP's allauth surface table",
)

#: ``allauth.account.urls`` — the local-account surface. Keyed by URL name, which is
#: the only stable handle allauth offers (routes move between versions, names do not).
ACCOUNT_SURFACE: Final[dict[str, Disposition]] = {
    # -- served ---------------------------------------------------------------
    "account_login": Disposition(
        SERVE,
        "the local password recovery floor (req-tap-auth-local) and the passkey page's "
        "documented fallback; rate-limited by allauth's login_failed limit",
    ),
    "account_logout": Disposition(SERVE, "session teardown; redirects to TAP's own front door"),
    "account_inactive": Disposition(SERVE, "terminal notice allauth redirects a deactivated account to"),
    # -- closed ---------------------------------------------------------------
    "account_set_password": Disposition(
        CLOSED,
        "a federated account has an unusable password by construction, so this view's "
        "only gate admits every federated user — self-issuing a local credential that "
        "bypasses evaluate_access permanently (tap#703)",
    ),
    "account_change_password": Disposition(
        CLOSED,
        "the second half of the same surface: it redirects a passwordless user to "
        "account_set_password, and an operator's password is changed out-of-band "
        "(manage.py changepassword), never over the web",
    ),
    "account_reset_password": Disposition(
        CLOSED,
        "a latent second mint path: reset resolves a user by User.email and ends in a "
        "usable password. TAP configures no EMAIL_BACKEND, so it is also non-functional "
        "today — closing it means a future EMAIL_BACKEND does not silently open it",
    ),
    "account_reset_password_done": Disposition(CLOSED, "terminal page of the closed reset flow"),
    "account_reset_password_from_key": Disposition(CLOSED, "key-confirmation step of the closed reset flow"),
    "account_reset_password_from_key_done": Disposition(CLOSED, "terminal page of the closed reset flow"),
    "account_signup": Disposition(
        CLOSED,
        "local self-signup is refused by TapAccountAdapter.is_open_for_signup; the URL is "
        "closed too so the refusal does not depend on one adapter hook staying overridden",
    ),
    "account_email": Disposition(
        CLOSED,
        "self-service mutation of User.email — the key of the TAP_AUTH_INITIAL_GRANTS map "
        "and of the linking-disabled check. A user with no verified address may mark any "
        "address primary, letting an insider squat an operator's address (tap#703)",
    ),
    "account_email_verification_sent": Disposition(CLOSED, "step of the closed email-management flow"),
    "account_confirm_email": Disposition(
        CLOSED,
        "inert under ACCOUNT_EMAIL_VERIFICATION='none'; closed rather than left as a "
        "reachable no-op on the auth path",
    ),
    "account_reauthenticate": Disposition(
        CLOSED,
        "re-confirms a password to unlock sensitive account views — all of which are "
        "closed above, so this has no reachable purpose",
    ),
    "account_confirm_login_code": Disposition(
        CLOSED,
        "login-by-code is not enabled (ACCOUNT_LOGIN_BY_CODE_ENABLED is off) yet allauth "
        "mounts the confirm step unconditionally",
    ),
}

#: ``allauth.socialaccount.urls`` — mounted under ``3rdparty/``.
SOCIALACCOUNT_SURFACE: Final[dict[str, Disposition]] = {
    "socialaccount_login_cancelled": Disposition(
        SERVE, "allauth redirects here when the user aborts at the IdP; a terminal notice"
    ),
    "socialaccount_login_error": Disposition(SERVE, "terminal notice for a failed provider handshake"),
    # Deliberately left served: these two are the account-LINKING surface, which is
    # `Issue# 702 - tap`'s subject (?process=connect) and the auto_provision signup form,
    # which is `Issue# 705 - tap`'s. Ruling on them here would pre-empt that work with a
    # different author's context. They are listed rather than omitted so the decision is
    # visible in the table instead of invisible in an include.
    "socialaccount_connections": Disposition(
        SERVE, "linking surface — deferred to tap#702, which owns the ?process=connect ruling"
    ),
    "socialaccount_signup": Disposition(
        SERVE, "the auto_provision:false landing — deferred to tap#705, which owns that flow"
    ),
}


def _closed_view(name: str, reason: str) -> Any:
    """Build the refusing view for one closed route.

    A closed route answers 403 with a page, for every method and every caller —
    authenticated or not. The reason travels with the view rather than being looked up
    at request time so a route can never answer with another route's ruling.
    """

    def closed(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        logger.warning(
            "[073c] refused closed allauth route: name=%s path=%s method=%s authenticated=%s",
            name,
            request.path,
            request.method,
            getattr(getattr(request, "user", None), "is_authenticated", False),
        )
        return render(
            request,
            "tap_web/auth/surface_closed.html",
            {"route_name": name, "reason": reason},
            status=403,
        )

    closed.__name__ = f"closed_{name}"
    closed.__qualname__ = closed.__name__
    closed.__doc__ = f"Closed allauth route '{name}': {reason}"
    return closed


def apply_surface(patterns: list[Any], dispositions: dict[str, Disposition], *, source: str) -> list[Any]:
    """Return ``patterns`` with every non-served route replaced by a refusing view.

    Names are preserved for both verdicts (see the module docstring): ``reverse()``
    keeps working, the request does not.
    """
    applied: list[Any] = []
    for pattern in patterns:
        name = getattr(pattern, "name", None)
        if not isinstance(pattern, URLPattern) or name is None:
            # Nothing allauth's account/socialaccount URLConfs ship today is an
            # unnamed pattern or a nested resolver. If that changes, the surface has
            # no handle to rule on it by — so it is not mounted at all.
            logger.warning("[253d] dropping unnameable allauth pattern from %s: %r", source, pattern)
            continue
        disposition = dispositions.get(name, UNCLASSIFIED)
        if disposition.verdict == SERVE:
            applied.append(pattern)
            continue
        if name not in dispositions:
            logger.warning(
                "[5ad1] closing UNCLASSIFIED allauth route: name=%s source=%s — rule on it in "
                "tap_auth.allauth_surface",
                name,
                source,
            )
        applied.append(URLPattern(pattern.pattern, _closed_view(name, disposition.reason), pattern.default_args, name))
    return applied


def assert_allauth_apps_accounted() -> None:
    """Fail closed if an allauth sub-app this surface does not mount is installed.

    ``allauth.urls`` mounts ``allauth.mfa``, ``allauth.usersessions`` and
    ``allauth.headless`` when those apps are installed. This module mounts the account,
    socialaccount and provider surfaces only. Installing one of the others would, under
    the wholesale include, have silently added an authentication surface; here it is a
    boot-time error naming the app, so the decision is made by a person.
    """
    accounted = {"allauth", "allauth.account", "allauth.socialaccount"}
    unaccounted = sorted(
        config.name
        for config in apps.get_app_configs()
        if config.name.startswith("allauth")
        and config.name not in accounted
        and not config.name.startswith("allauth.socialaccount.providers.")
    )
    if unaccounted:
        raise ImproperlyConfigured(
            "tap_auth.allauth_surface does not mount these installed allauth apps: "
            f"{', '.join(unaccounted)}. Add their routes to the surface table (with a "
            "disposition per route) before installing them."
        )


def tap_allauth_urlpatterns() -> list[Any]:
    """The allauth routes TAP mounts under ``/auth/`` — the replacement for
    ``include("allauth.urls")``.

    Order mirrors allauth's own: account, then the ``3rdparty/`` socialaccount routes,
    then the provider routes (``oidc/<provider_id>/login/`` and its callback). Provider
    routes are mounted **wholesale and deliberately**: they are the federated login path
    this change exists to protect, they carry no local-credential surface, and their
    number and names are a function of the configured providers rather than of the
    allauth version — so a per-name table there would be a table of the operator's boot
    profile, not of an inherited dependency surface.

    allauth's deprecated ``social/*`` redirect aliases are not mounted: they are
    unnamed permanent redirects to the ``3rdparty/`` routes, nothing reverses them, and
    an alias is a second name for a surface that should have one.
    """
    assert_allauth_apps_accounted()

    account_urls = import_module("allauth.account.urls")
    socialaccount_urls = import_module("allauth.socialaccount.urls")
    allauth_urls = import_module("allauth.urls")

    patterns: list[Any] = []
    patterns += apply_surface(list(account_urls.urlpatterns), ACCOUNT_SURFACE, source="allauth.account.urls")
    patterns += [
        path(
            "3rdparty/",
            include(
                apply_surface(
                    list(socialaccount_urls.urlpatterns),
                    SOCIALACCOUNT_SURFACE,
                    source="allauth.socialaccount.urls",
                )
            ),
        )
    ]
    patterns += allauth_urls.build_provider_urlpatterns()
    return patterns
