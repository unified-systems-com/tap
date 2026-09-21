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

import secrets
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver, include, path, reverse

from tap_auth.allauth_surface import ACCOUNT_SURFACE, SERVE, apply_surface
from tap_auth.models import ExternalIdentity

# Generated per run, never literals. A credential written into the tree is a
# credential, however clearly it is labelled a fixture — and every scanner that reads
# this file is right to say so. Generating them also proves the assertions below do not
# depend on any particular value.
_OPERATOR_SECRET = secrets.token_urlsafe(24)
_MINTED_SECRET = secrets.token_urlsafe(24)


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


def _never_dispatched(request: HttpRequest) -> HttpResponse:
    """Stand-in view for the synthetic patterns below.

    Typed rather than a bare `lambda` so mypy has something real to check —
    and it raises, so a test that expects the surface to have REPLACED it fails loudly
    instead of quietly asserting against a view that answered.
    """
    raise AssertionError("synthetic test view reached — the surface did not replace it")


def _an_installed_provider_id() -> str:
    """The id of a provider class this deployment actually installs.

    Hardcoding `github` here failed in CI and passed locally (`PR# 717 - tap`): the
    ruling is DERIVED from allauth's registry, so `github_login` is a ruled name only
    where the github provider app is installed. The core_ci profile does not install it,
    so the route was correctly CLOSED and the test asserting it stayed open was wrong.
    Deriving the id makes these tests say what they mean — "a route this deployment
    rules on" — in every profile.
    """
    from allauth.socialaccount import providers

    ids = sorted(str(cls.id) for cls in providers.registry.get_class_list())
    assert ids, "no provider installed — the provider-surface tests would be vacuous"
    return ids[0]


def _auth_routes() -> list[tuple[str, str]]:
    """Every named route mounted under `/auth/`, as (name, pattern string) PAIRS.

    Walks the live root URLConf rather than any checked-in list, so this sees what the
    server actually serves — including anything allauth adds on a bump.

    Pairs, not a dict: a dict silently collapses two patterns sharing a name, and the
    surface table rules by name. A duplicate would then be invisible to the inventory
    while riding another route's verdict (`PR# 717 - tap`).
    """
    found: list[tuple[str, str]] = []

    def walk(patterns: list[Any], prefix: str) -> None:
        for entry in patterns:
            route = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, route)
            elif isinstance(entry, URLPattern):
                assert entry.name is not None, f"unnamed pattern mounted under /auth/: {route!r}"
                found.append((entry.name, route))

    for entry in get_resolver().url_patterns:
        if isinstance(entry, URLResolver) and str(entry.pattern) == "auth/":
            walk(entry.url_patterns, "auth/")
    return found


def _auth_route_names() -> list[str]:
    return [name for name, _ in _auth_routes()]


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

    Deriving them from the mounting builder makes THIS set tautological, so it buys no
    safety on its own — the per-installed-provider test below is what actually guards
    the provider surface, by comparing against allauth's registry.
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
    assert set(_auth_route_names()) == expected


@pytest.mark.spec("req-tap-auth-allauth-surface-1")
def test_provider_routes_are_exactly_login_and_callback_per_installed_provider() -> None:
    """The guard on the provider half of the surface (`PR# 717 - tap`).

    `_provider_route_names()` derives from the same builder that mounts, so on its own it
    is tautological — it cannot notice a provider URLConf growing a third route. This
    test supplies the INDEPENDENT source: allauth's provider *registry*, which lists the
    provider classes the installed apps registered. TAP's provider contract is exactly
    login-initiation plus callback per provider, so the expected set is derivable from
    the registry alone — `{<id>_login, <id>_callback}` — and compared against what the
    URLConf actually mounts.

    Derived, so an added provider TYPE (`PR# 688 - tap`'s `github_oauth` →
    `github_login` / `github_callback`) passes with no edit here. Independent, so an
    added provider ROUTE fails.

    Not hypothetical, and a suffix check would not have been enough: read against the
    pinned allauth 65.19.0 wheel, installing one more provider app would mount
    `saml_acs`, `saml_sls`, `saml_metadata`, `facebook_login_by_token` — and
    `apple_finish_callback`, which ENDS IN `_callback` and would sail through a shape
    test. Each is a real authentication endpoint; each now arrives as a named failure
    asking for a ruling.
    """
    from allauth.socialaccount import providers

    expected = {f"{cls.id}_{suffix}" for cls in providers.registry.get_class_list() for suffix in ("login", "callback")}
    mounted = _provider_route_names()
    assert mounted == expected, (
        f"provider URLConf(s) mount routes TAP has not ruled on: {sorted(mounted - expected)} "
        f"(missing: {sorted(expected - mounted)}). Rule on each in tap_auth.allauth_surface "
        "before serving it."
    )


@pytest.mark.spec("req-tap-auth-allauth-surface-1")
def test_no_two_mounted_routes_share_a_name() -> None:
    """The precondition the whole table rests on: a name identifies ONE route.

    Without this the inventory above can pass while a second pattern rides an existing
    name — and at a SERVE name that is a new view served by inheritance, which is the
    failure class this module exists to end (`PR# 717 - tap`).
    """
    names = _auth_route_names()
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == [], f"two routes under /auth/ share a URL name: {duplicates}"


@pytest.mark.spec("req-tap-auth-allauth-surface-1")
def test_every_account_route_in_the_table_is_actually_mounted() -> None:
    """The table is an inventory of the real surface, not a wish list.

    A disposition for a route allauth no longer mounts is a declaration no code reads —
    it would read as coverage while guarding nothing (`tap#700` rule 4).
    """
    mounted = _auth_route_names()
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
            {"password1": _MINTED_SECRET, "password2": _MINTED_SECRET},
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
            {"login": user.get_username(), "password": _MINTED_SECRET},
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
            password=_OPERATOR_SECRET,
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
            {"login": operator.get_username(), "password": _OPERATOR_SECRET},
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
            {"login": operator.get_username(), "password": _OPERATOR_SECRET},
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
    unruled = path("brand-new-account-view/", _never_dispatched, name="account_brand_new")
    (applied,) = apply_surface([unruled], {}, source="test")
    assert applied.name == "account_brand_new"

    request = RequestFactory().get("/auth/brand-new-account-view/")
    request.user = AnonymousUser()  # the auth context processor reads it while rendering
    assert applied.callback(request).status_code == 403


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
@pytest.mark.parametrize("order", [("login/", "login/v2/"), ("login/v2/", "login/")])
def test_every_occurrence_of_a_duplicated_name_is_closed(order: tuple[str, str]) -> None:
    """Two patterns named `account_login` — a SERVE name — and BOTH are closed.

    Parametrised on arrival order on purpose. Closing only "the repeat" reads as
    fail-closed and is not: a future allauth release that PREPENDS a pattern under an
    existing SERVE name would have its new callback served, and the legitimate route
    closed instead. Which pattern comes first is decided by allauth's URLConf order, not
    by TAP, so the only version of this guard that does not depend on luck is the one
    that closes every occurrence (`PR# 717 - tap`).

    The cost is understood and accepted: if allauth ever duplicates `account_login`, the
    local recovery floor closes until someone rules on it. That is the right direction
    for a surface whose whole purpose is to fail closed, and the inventory test names it
    the moment it happens.
    """
    patterns = [path(route, _never_dispatched, name="account_login") for route in order]
    applied = apply_surface(patterns, ACCOUNT_SURFACE, source="test")

    assert len(applied) == 2
    for pattern, original in zip(applied, patterns, strict=True):
        assert pattern.name == "account_login"
        assert pattern.callback is not original.callback, "a duplicated name was served by inheritance"
        request = RequestFactory().get("/auth/" + str(pattern.pattern))
        request.user = AnonymousUser()
        assert pattern.callback(request).status_code == 403


@pytest.mark.django_db
@pytest.mark.spec("req-tap-auth-allauth-surface-3")
def test_the_403_page_does_not_publish_the_ruling() -> None:
    """The reasons in the table are a threat model — "bypasses evaluate_access", "squat
    an operator's address". They belong in the log, where the operator and any AI helper
    reading it get the whole ruling; an anonymous GET is not their audience
    (`PR# 717 - tap`). The route NAME is fine: it is the URL the caller already typed.
    """
    body = _localhost().get(reverse("account_set_password")).content.decode()
    assert "account_set_password" in body
    assert "evaluate_access" not in body
    assert ACCOUNT_SURFACE["account_set_password"].reason not in body


# --------------------------------------------------------------------------- #
# The two signals the surface emits: a refusal (the guard working) and a FLAW
# (the guard reporting that its own table is out of date).
# --------------------------------------------------------------------------- #


@pytest.mark.spec("req-tap-auth-allauth-surface-3")
def test_the_refusal_log_never_carries_a_credential_bearing_path(caplog) -> None:
    """Two closed routes carry a SECRET IN THE PATH.

    `account_confirm_email` is `/auth/confirm-email/<key>/` and
    `account_reset_password_from_key` is `/auth/password/reset/key/<uid>-<key>/`.
    Logging `request.path` on refusal would copy a confirmation or reset token into
    the operator log — and into every downstream log sink — from an unauthenticated
    GET, which is the opposite of what closing the route is for. The route NAME
    identifies the route; the path adds only the secret (`PR# 717 - tap` review).

    Asserted against the whole captured record set, not just the message template, so
    a future edit that re-adds the path through `extra=` or a context field fails too.
    """
    (applied,) = apply_surface(
        [path("password/reset/key/<uidb36>-<key>/", _never_dispatched, name="account_reset_password_from_key")],
        ACCOUNT_SURFACE,
        source="test",
    )
    leaked = "s3cret-reset-key-" + secrets.token_urlsafe(8)
    request = RequestFactory().get(f"/auth/password/reset/key/Nw-{leaked}/")
    request.user = AnonymousUser()

    with caplog.at_level("WARNING", logger="tap_auth.allauth_surface"):
        assert applied.callback(request).status_code == 403

    assert caplog.records, "a refusal must still be logged — the fix is redaction, not silence"
    haystack = "\n".join(r.getMessage() + repr(getattr(r, "message_data", "")) for r in caplog.records)
    assert leaked not in haystack, "the reset key reached the log"
    assert "account_reset_password_from_key" in haystack, "the route name is what identifies the refusal"


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
def test_an_unruled_route_reports_a_security_flaw(caplog) -> None:
    """A route nobody ruled on is an invariant violation, not log noise.

    Refusing a caller is the guard working and stays a plain WARNING. Finding a route
    this deployment has never decided about means the TABLE is out of date — TAP core
    owns that table, so it is a `CodeFlaw`, security-tagged, `fail_closed_continue`
    (closed on arrival, boot continues). The distinction is the point: only one of the
    two events is a defect, and a bare warning among the boot warnings is exactly what
    gets scrolled past.
    """
    with caplog.at_level("ERROR", logger="tap_auth.allauth_surface"):
        apply_surface([path("brand-new/", _never_dispatched, name="account_brand_new")], {}, source="test")

    flaws = [getattr(r, "message_data", {}) for r in caplog.records if getattr(r, "message_code", "") == "FLAW"]
    assert len(flaws) == 1, f"expected exactly one FLAW, got {flaws}"
    flaw = flaws[0]
    assert flaw["invariant_id"] == "allauth_route_classified"
    assert flaw["flaw_class"] == "code"
    assert "security" in flaw["flaw_tags"]
    assert flaw["handling"] == "fail_closed_continue"
    assert flaw["context"]["route_name"] == "account_brand_new"
    assert "account_brand_new" in "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
def test_a_duplicated_route_name_reports_a_security_flaw(caplog) -> None:
    """Same reasoning for a name mounted twice: a name carries exactly one ruling, so
    a collision means no disposition can be applied unambiguously. Every occurrence is
    closed AND the collision is reported, so the fail-closed behaviour is not the only
    record that it happened.
    """
    patterns = [path(r, _never_dispatched, name="account_login") for r in ("login/", "login/v2/")]
    with caplog.at_level("ERROR", logger="tap_auth.allauth_surface"):
        apply_surface(patterns, ACCOUNT_SURFACE, source="test")

    flaws = [getattr(r, "message_data", {}) for r in caplog.records if getattr(r, "message_code", "") == "FLAW"]
    assert flaws, "a duplicated route name must be reported, not only closed"
    assert all(f["invariant_id"] == "allauth_route_name_unique" for f in flaws)
    assert all(f["flaw_class"] == "code" and "security" in f["flaw_tags"] for f in flaws)


# --------------------------------------------------------------------------- #
# The provider half — ruled at runtime, not only asserted in CI.
# --------------------------------------------------------------------------- #


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
def test_installed_provider_login_and_callback_are_still_served() -> None:
    """The regression that would matter most: closing the provider surface must not
    close the way in. Every `<id>_login` / `<id>_callback` of an INSTALLED provider
    class stays served by allauth's own view — asserted against the real mounted
    URLConf, so it fails if `provider_dispositions()` ever stops deriving from the
    registry the mounted routes come from.
    """
    from allauth.socialaccount import providers

    from tap_auth.allauth_surface import tap_allauth_urlpatterns

    served: dict[str, Any] = {}

    def walk(patterns: list[Any]) -> None:
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(list(entry.url_patterns))
            elif entry.name is not None:
                served[entry.name] = entry.callback

    walk(tap_allauth_urlpatterns())

    expected = {f"{cls.id}_{suffix}" for cls in providers.registry.get_class_list() for suffix in ("login", "callback")}
    assert expected, "no provider installed — this test would be vacuous"
    for name in sorted(expected):
        assert name in served, f"{name} is no longer mounted"
        assert not served[name].__name__.startswith("closed_"), f"{name} was closed — provider login is broken"


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
def test_an_extra_route_inside_a_provider_urlconf_is_closed(caplog) -> None:
    """The Codex Medium from the `PR# 717 - tap` review, made concrete.

    Provider patterns arrive nested under a per-provider resolver, so before this they
    were appended wholesale — `assert_allauth_apps_accounted` exempts every
    `allauth.socialaccount.providers.*` app, so nothing refused them. Against the pinned
    allauth 65.19.0 wheel the real instances are `saml_acs` / `saml_sls` /
    `saml_metadata` / `apple_finish_callback`: authentication endpoints that a profile
    enabling one more provider would have served.

    Modelled here with a resolver carrying one ruled route and one unruled one, which
    also proves the descent — a flat-only implementation would drop the whole resolver.
    """
    from tap_auth.allauth_surface import provider_dispositions

    provider = _an_installed_provider_id()
    inner = [
        path("login/", _never_dispatched, name=f"{provider}_login"),
        path("acs/", _never_dispatched, name=f"{provider}_acs"),
    ]
    applied = apply_surface(
        [path(f"{provider}/", include((inner, provider)))], provider_dispositions(), source="test"
    )
    (resolver,) = applied
    assert isinstance(resolver, URLResolver), "the provider resolver was dropped, not descended into"
    by_name = {p.name: p for p in resolver.url_patterns if isinstance(p, URLPattern)}

    assert by_name[f"{provider}_login"].callback is inner[0].callback, "a ruled provider route must stay served"
    closed_route = by_name[f"{provider}_acs"]
    assert closed_route.callback is not inner[1].callback, "an unruled provider route was served"
    request = RequestFactory().get(f"/auth/{provider}/acs/")
    request.user = AnonymousUser()
    assert closed_route.callback(request).status_code == 403


@pytest.mark.spec("req-tap-auth-allauth-surface-6")
def test_the_mounted_urlconf_closes_an_unruled_provider_route(monkeypatch) -> None:
    """The guard at the INTEGRATION point, not at `apply_surface`.

    Written because the first version of these tests did not catch the regression they
    exist for: exercising `apply_surface` directly passes whether or not
    `tap_allauth_urlpatterns` actually routes the provider patterns through it, and
    asserting that real provider routes stay OPEN passes under a wholesale append too.
    Reverting the call to `patterns += build_provider_urlpatterns()` left both green.

    The real installed set (github, openid_connect) mounts nothing beyond login and
    callback, so there is nothing for a live assertion to catch — the ratchet only bites
    when a provider mounting a third route is installed. This supplies exactly that: a
    provider URLConf carrying a SAML-shaped extra endpoint, through the real mounting
    function.
    """
    import allauth.urls as allauth_urls

    from tap_auth.allauth_surface import tap_allauth_urlpatterns

    provider = _an_installed_provider_id()
    inner = [
        path("login/", _never_dispatched, name=f"{provider}_login"),
        path("acs/", _never_dispatched, name=f"{provider}_acs"),
    ]
    monkeypatch.setattr(
        allauth_urls,
        "build_provider_urlpatterns",
        lambda: [path(f"{provider}/", include((inner, provider)))],
    )

    mounted: dict[str, Any] = {}

    def walk(patterns: list[Any]) -> None:
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(list(entry.url_patterns))
            elif entry.name is not None:
                mounted.setdefault(entry.name, entry.callback)

    walk(tap_allauth_urlpatterns())

    assert mounted[f"{provider}_login"] is inner[0].callback, "a ruled provider route must stay served"
    assert mounted[f"{provider}_acs"] is not inner[1].callback, (
        "an unruled provider route reached the mounted URLConf — the provider patterns are being "
        "appended without a ruling"
    )
