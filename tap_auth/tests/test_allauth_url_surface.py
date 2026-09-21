"""The allauth URL surface TAP mounts, driven through the URLs (req-tap-auth-allauth-surface).

Every assertion here goes through the mounted route with a real request. That is
deliberate: the defect this file pins (`tap#703`) was invisible to the existing
`tap_auth` tests precisely because they call adapter hooks directly. What matters is
what the framework ROUTES, not what a method returns when called by hand — a test that
calls `PasswordSetView` would have said nothing about whether the view is reachable.

Three things are pinned:

1. **The inventory.** The exact set of URL names reachable under `/auth/`. An allauth
   version bump that mounts a new account view (Renovate merges these routinely) fails
   here by name instead of silently widening the authentication surface.
2. **The refusal.** A federated user — unusable password, exactly as social signup
   leaves them — cannot mint a local credential through `/auth/password/set/`, nor
   through the sibling change/reset/email surfaces.
3. **The floor.** The operator recovery path (`local_password_enabled` + a password set
   out-of-band + `/auth/login/`) still works. Without this half, (2) would only prove
   something was broken.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver, path, reverse

from tap_auth.allauth_surface import ACCOUNT_SURFACE, SERVE, apply_surface
from tap_auth.models import ExternalIdentity

_OPERATOR_PASSWORD = "operator-recovery-floor-pw-9471"  # nosec B105 — test fixture credential
_MINTED_PASSWORD = "self-minted-bypass-pw-13795"  # nosec B105 — test fixture credential


# ---------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------


def _localhost() -> Client:
    """A client whose Host passes ALLOWED_HOSTS.

    Not cosmetic: the default `testserver` host raises `DisallowedHost` and returns 400
    for every request — a probe run that way would report "refused" while never having
    reached the view, which is the exact shape of a check that passes by reading nothing.
    """
    return Client(SERVER_NAME="localhost")


def _auth_routes() -> dict[str, str]:
    """Every named route mounted under `/auth/`, as name -> pattern string.

    Walks the live root URLConf rather than any checked-in list, so this sees what the
    server actually serves — including anything allauth adds on a bump.
    """
    found: dict[str, str] = {}

    def walk(patterns: list[Any], prefix: str) -> None:
        for entry in patterns:
            route = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, route)
            elif isinstance(entry, URLPattern):
                assert entry.name is not None, f"unnamed pattern mounted under /auth/: {route!r}"
                found[entry.name] = route

    for entry in get_resolver().url_patterns:
        if isinstance(entry, URLResolver) and str(entry.pattern) == "auth/":
            walk(entry.url_patterns, "auth/")
    return found


#: TAP's own auth routes.
_TAP_ROUTES = {
    "passkey_login",
    "passkey_login_options",
    "passkey_login_verify",
    "passkey_enroll",
    "passkey_enroll_options",
    "passkey_enroll_verify",
    "no_access",
}

#: The allauth `3rdparty/` surface. Enumerated, like the account surface: its size is a
#: function of the allauth VERSION, so a bump that adds one must be ruled on.
_SOCIALACCOUNT_ROUTES = {
    "socialaccount_login_cancelled",
    "socialaccount_login_error",
    "socialaccount_signup",
    "socialaccount_connections",
}


def _provider_route_names() -> set[str]:
    """The provider login/callback names, DERIVED from the same builder that mounts them.

    Deliberately not enumerated. The account surface above is inherited from the allauth
    version and must be ruled on route by route; the provider routes are a function of
    which provider TYPES this deployment installs — an operator/roadmap decision, not a
    dependency surface. Enumerating them would make `PR# 688 - tap` (the `github_oauth`
    provider) fail a test about allauth's account views, which would teach the next
    author to edit the list rather than read it.
    """
    from allauth.urls import build_provider_urlpatterns

    names: set[str] = set()

    def walk(patterns: list[Any]) -> None:
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns)
            elif entry.name is not None:
                names.add(entry.name)

    walk(build_provider_urlpatterns())
    return names


#: Closed routes that take no URL arguments, so a client can drive them by name.
_ARGLESS_CLOSED = sorted(
    name
    for name, disposition in ACCOUNT_SURFACE.items()
    if disposition.verdict != SERVE and name not in {"account_confirm_email", "account_reset_password_from_key"}
)


# ---------------------------------------------------------------------------------
# 1. the inventory
# ---------------------------------------------------------------------------------


@pytest.mark.spec("req-tap-auth-allauth-surface-1")
def test_auth_url_inventory_is_exactly_the_declared_set() -> None:
    """The durable deliverable: `/auth/` serves this set of names and no other.

    A new allauth route arrives here as a failure naming it, which is the only moment
    anyone will ever look at it. Adding a name to this set is a deliberate act that
    requires a disposition in `tap_auth.allauth_surface` alongside it.
    """
    expected = _TAP_ROUTES | _SOCIALACCOUNT_ROUTES | _provider_route_names() | set(ACCOUNT_SURFACE)
    assert set(_auth_routes()) == expected


@pytest.mark.spec("req-tap-auth-allauth-surface-1")
def test_every_account_route_in_the_table_is_actually_mounted() -> None:
    """The table is an inventory of the real surface, not a wish list.

    A disposition for a route allauth no longer mounts is a declaration no code reads —
    it would read as coverage while guarding nothing (`tap#700` rule 4).
    """
    mounted = _auth_routes()
    assert sorted(ACCOUNT_SURFACE) == sorted(name for name in mounted if name.startswith("account_"))


@pytest.mark.spec("req-tap-auth-allauth-surface-1")
def test_password_set_is_mounted_at_the_path_the_review_named() -> None:
    """Anchors the inventory to the concrete URL, so a rename cannot quietly move it."""
    assert reverse("account_set_password") == "/auth/password/set/"
    assert reverse("account_login") == "/auth/login/"


# ---------------------------------------------------------------------------------
# 2. the refusal — the load-bearing negative test
# ---------------------------------------------------------------------------------


@pytest.mark.django_db
class TestFederatedUserCannotMintALocalPassword:
    """`tap#703`: the self-service mint, driven through the mounted URL."""

    def _federated_user(self) -> Any:
        """A user shaped exactly as social signup leaves one.

        `DefaultSocialAccountAdapter.populate_user` calls `set_unusable_password()`, and
        `TapSocialAccountAdapter._sync_external_identity` stamps the deterministic
        username. Both are reproduced here — the username matters because it is the half
        of the credential the attacker must know, and it is computable from public inputs.
        """
        user = get_user_model().objects.create_user(
            username=ExternalIdentity.generate_username("example-google", "subject-1"),
            email="admitted-once@example.test",
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return user

    @pytest.mark.spec("req-tap-auth-allauth-surface-2")
    def test_password_set_refuses_a_federated_user_and_mints_nothing(self, settings) -> None:
        """THE test. A federated user POSTs the set-password form and is refused; no
        usable credential exists afterwards, and the local login path still rejects it.

        `TAP_LOCAL_PASSWORD_ENABLED` is left TRUE on purpose — the recovery floor is on
        in `boot/operator_sso.boot.json`, so this is the deployed condition, and the
        refusal must not depend on the flag.
        """
        settings.TAP_LOCAL_PASSWORD_ENABLED = True
        cache.clear()
        user = self._federated_user()
        client = _localhost()
        client.force_login(user)

        assert client.get(reverse("account_set_password")).status_code == 403
        posted = client.post(
            reverse("account_set_password"),
            {"password1": _MINTED_PASSWORD, "password2": _MINTED_PASSWORD},
        )
        assert posted.status_code == 403

        user.refresh_from_db()
        assert not user.has_usable_password(), "the federated user minted a local credential"

        # And the credential they tried to mint does not authenticate: the bypass is
        # closed end to end, not merely at the form.
        client.logout()
        login = _localhost()
        login.post(
            reverse("account_login"),
            {"login": user.get_username(), "password": _MINTED_PASSWORD},
        )
        assert "_auth_user_id" not in login.session

    @pytest.mark.spec("req-tap-auth-allauth-surface-2")
    def test_refusal_does_not_consult_the_local_password_flag(self, settings) -> None:
        """A guard may never be conditional on the value it guards (`tap#700` rule 2).

        `local_password_enabled` decides who may USE an issued credential. It was never a
        decision to let a federated principal ISSUE one, so the refusal is identical in
        both states.
        """
        user = self._federated_user()
        for enabled in (True, False):
            settings.TAP_LOCAL_PASSWORD_ENABLED = enabled
            client = _localhost()
            client.force_login(user)
            assert client.get(reverse("account_set_password")).status_code == 403

    @pytest.mark.spec("req-tap-auth-allauth-surface-2")
    def test_anonymous_callers_are_refused_too(self) -> None:
        """Closed means closed for everyone — not "login_required and then closed"."""
        assert _localhost().get(reverse("account_set_password")).status_code == 403

    @pytest.mark.spec("req-tap-auth-allauth-surface-3")
    @pytest.mark.parametrize("name", _ARGLESS_CLOSED)
    def test_every_closed_account_route_refuses(self, name: str) -> None:
        """The sibling surfaces, not just the one the review named.

        `password/change/` is the other half of the same mint, the `password/reset/`
        family is a latent second one (reset ends in a usable password and resolves its
        user by `User.email`), and `email/` is self-service mutation of the very field
        the grant map and the linking check key on.
        """
        client = _localhost()
        assert client.get(reverse(name)).status_code == 403
        assert client.post(reverse(name), {}).status_code == 403

    @pytest.mark.spec("req-tap-auth-allauth-surface-3")
    def test_closed_routes_keep_their_names_resolvable(self) -> None:
        """Why closed rather than unmounted: allauth reverses these names from code that
        has nothing to do with the closed view — `account/middleware.py` reverses
        `account_email` on every 404 under the mount prefix, and `account/fields.py`
        reverses `account_reset_password` while rendering the login form. Unmounting
        them would raise NoReverseMatch inside the login page itself, i.e. would break
        the recovery floor this change exists to protect.
        """
        for name in ("account_email", "account_reset_password", "account_signup"):
            assert reverse(name).startswith("/auth/")


# ---------------------------------------------------------------------------------
# 3. the floor — the necessary companion
# ---------------------------------------------------------------------------------


@pytest.mark.django_db
class TestOperatorRecoveryFloorStillWorks:
    """Without these, the tests above prove only that something was broken."""

    def _operator(self) -> Any:
        """An operator account as the out-of-band paths create one: a real, usable
        password set by `createsuperuser` / `changepassword` / the bootstrap path in
        `tap_auth.sync` — never through a web form."""
        return get_user_model().objects.create_user(
            username="recovery-operator",
            password=_OPERATOR_PASSWORD,
        )

    @pytest.mark.spec("req-tap-auth-allauth-surface-4")
    def test_operator_can_still_sign_in_locally(self, settings) -> None:
        """The floor `boot/operator_sso.boot.json` documents: "Local password login is
        left enabled as a recovery floor so a misconfigured OIDC path cannot lock the
        operator out." Still true after this change."""
        settings.TAP_LOCAL_PASSWORD_ENABLED = True
        cache.clear()
        operator = self._operator()
        client = _localhost()
        client.post(
            reverse("account_login"),
            {"login": operator.get_username(), "password": _OPERATOR_PASSWORD},
        )
        assert client.session.get("_auth_user_id") == str(operator.pk)

    @pytest.mark.spec("req-tap-auth-allauth-surface-4")
    def test_the_login_page_the_floor_depends_on_still_renders(self, settings) -> None:
        """The login form renders allauth internals that reverse `account_reset_password`
        and `account_signup` — both closed. Closing a route must not 500 the page that
        is the whole recovery floor."""
        settings.TAP_LOCAL_PASSWORD_ENABLED = True
        cache.clear()
        assert _localhost().get(reverse("account_login")).status_code == 200
        assert _localhost().get(reverse("passkey_login")).status_code == 200

    @pytest.mark.spec("req-tap-auth-allauth-surface-5")
    def test_disabling_local_passwords_binds_through_the_login_url(self, settings) -> None:
        """`local_password_enabled: false` must actually prevent local password login —
        a declaration that no code enforces is a defect (`tap#700` rule 4). Asserted
        through the mounted URL with CORRECT credentials, not at the backend."""
        settings.TAP_LOCAL_PASSWORD_ENABLED = False
        cache.clear()
        operator = self._operator()
        client = _localhost()
        client.post(
            reverse("account_login"),
            {"login": operator.get_username(), "password": _OPERATOR_PASSWORD},
        )
        assert "_auth_user_id" not in client.session


# ---------------------------------------------------------------------------------
# the third state
# ---------------------------------------------------------------------------------


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
def test_an_unruled_route_is_closed_rather_than_served() -> None:
    """The state that matters on the next allauth bump: not "served" and not "closed"
    but NEVER RULED ON. It must land closed — fail-closed is what makes the inventory
    test a warning rather than a post-mortem.
    """
    unruled = path("brand-new-account-view/", lambda request: None, name="account_brand_new")
    (applied,) = apply_surface([unruled], {}, source="test")
    assert applied.name == "account_brand_new"

    request = RequestFactory().get("/auth/brand-new-account-view/")
    request.user = AnonymousUser()  # the auth context processor reads it while rendering
    assert applied.callback(request).status_code == 403
