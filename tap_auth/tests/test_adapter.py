"""Social adapter + ExternalIdentity tests (increment 3 — req-tap-auth-google-oidc,
req-tap-auth-external-identity).

Layer-1 of the OIDC test strategy: the security decision (``evaluate_access``)
is a pure function exercised exhaustively with synthetic claims (no network, no
DB), and the adapter's gate/provisioning logic is tested directly. Real-Google
end-to-end is the manual smoke.
"""

from __future__ import annotations

from typing import Any

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory

from tap_auth.adapter import TapSocialAccountAdapter
from tap_auth.models import ExternalIdentity, ExternalIdentityStatus
from tap_auth.providers import ProviderConfig, get_provider

PROVIDER_ID = "example-google"


def _provider_raw(**over) -> dict:
    raw = {
        "id": PROVIDER_ID,
        "type": "google_oidc",
        "display_name": "example.com (Google)",
        "allowed_domains": ["example.com"],
    }
    raw.update(over)
    return raw


def _claims(**over) -> dict:
    c = {
        "sub": "google-sub-123",
        "email": "operator@example.com",
        "email_verified": True,
        "hd": "example.com",
        "name": "George",
    }
    c.update(over)
    return c


def _eval(provider_raw: dict, claims: dict):
    cfg = ProviderConfig.from_dict(provider_raw)
    return get_provider(cfg.type).evaluate_access(cfg, claims)


# --------------------------------------------------------------------------- #
# evaluate_access — the pure security core
# --------------------------------------------------------------------------- #


class TestEvaluateAccess:
    def test_allow_verified_in_domain_and_allowlist(self):
        d = _eval(_provider_raw(allowed_emails=["operator@example.com"]), _claims())
        assert d.allowed is True
        assert d.matched_domain == "example.com"
        assert d.verified_email == "operator@example.com"

    def test_allow_domain_only_no_allowlist(self):
        assert _eval(_provider_raw(), _claims()).allowed is True

    def test_deny_email_not_verified(self):
        d = _eval(_provider_raw(), _claims(email_verified=False))
        assert d.allowed is False and d.reason == "email_not_verified"

    def test_email_verified_string_true_accepted(self):
        assert _eval(_provider_raw(), _claims(email_verified="true")).allowed is True

    def test_deny_domain_not_allowed_by_hd(self):
        d = _eval(_provider_raw(), _claims(hd="evil.com", email="x@evil.com"))
        assert d.allowed is False and d.reason == "domain_not_allowed"

    def test_deny_no_hd_no_fallback(self):
        # consumer Google account: no hd, fallback off → denied (no silent email-domain match)
        c = _claims(email="operator@example.com")
        c.pop("hd")
        d = _eval(_provider_raw(), c)
        assert d.allowed is False and d.reason == "domain_not_allowed"

    def test_allow_via_email_domain_fallback_when_enabled(self):
        c = _claims(email="operator@example.com")
        c.pop("hd")
        d = _eval(_provider_raw(email_domain_fallback=True), c)
        assert d.allowed is True and d.matched_domain == "example.com"

    def test_fallback_still_requires_verified_email(self):
        c = _claims(email="operator@example.com", email_verified=False)
        c.pop("hd")
        d = _eval(_provider_raw(email_domain_fallback=True), c)
        assert d.allowed is False and d.reason == "email_not_verified"

    def test_deny_account_not_allowlisted(self):
        d = _eval(_provider_raw(allowed_emails=["someone-else@example.com"]), _claims())
        assert d.allowed is False and d.reason == "account_not_allowlisted"

    def test_hd_takes_precedence_over_email_domain(self):
        # hd is the trustworthy claim; an attacker-controlled email domain must not widen access
        d = _eval(
            _provider_raw(allowed_domains=["example.com"]), _claims(hd="example.com", email="personal@example.net")
        )
        # email domain (example.net) is NOT allowed, but hd (example.com) IS → matched on hd
        assert d.allowed is True and d.matched_domain == "example.com"


# --------------------------------------------------------------------------- #
# ExternalIdentity model
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestExternalIdentityModel:
    def test_redacted_subject_hides_full_value(self):
        u = get_user_model().objects.create_user(username="u1")
        ei = ExternalIdentity.objects.create(
            provider_id=PROVIDER_ID, provider_type="google_oidc", subject="super-secret-sub", user=u
        )
        assert "super-secret-sub" not in ei.redacted_subject
        assert ei.redacted_subject.startswith("sub#")

    def test_generate_username_stable_and_prefixed(self):
        a = ExternalIdentity.generate_username(PROVIDER_ID, "sub-1")
        b = ExternalIdentity.generate_username(PROVIDER_ID, "sub-1")
        assert a == b and a.startswith(f"ext-{PROVIDER_ID}-") and len(a) <= 150

    def test_provider_subject_unique(self):
        from django.db import IntegrityError

        u = get_user_model().objects.create_user(username="u2")
        ExternalIdentity.objects.create(provider_id=PROVIDER_ID, provider_type="google_oidc", subject="dup", user=u)
        with pytest.raises(IntegrityError):
            ExternalIdentity.objects.create(provider_id=PROVIDER_ID, provider_type="google_oidc", subject="dup", user=u)


# --------------------------------------------------------------------------- #
# Social adapter — gate + provisioning
# --------------------------------------------------------------------------- #


def _sociallogin(claims: dict, *, is_existing: bool = False) -> SocialLogin:
    account = SocialAccount(provider=PROVIDER_ID, uid=claims["sub"], extra_data=claims)
    sl = SocialLogin(account=account)
    sl.user = get_user_model()(username="pending", email=claims.get("email", ""))
    sl.state = {}
    # is_existing is a property on SocialLogin derived from account.pk; emulate it
    sl.account.pk = 1 if is_existing else None
    return sl


@pytest.mark.django_db
class TestSocialAdapter:
    def _request(self):
        return RequestFactory().get("/auth/oidc/example-google/login/callback/")

    def test_pre_social_login_allows_valid(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider_raw(allowed_emails=["operator@example.com"])]
        # no raise == allowed
        TapSocialAccountAdapter().pre_social_login(self._request(), _sociallogin(_claims()))

    def test_pre_social_login_denies_wrong_domain(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider_raw()]
        with pytest.raises(ImmediateHttpResponse) as exc:
            TapSocialAccountAdapter().pre_social_login(
                self._request(), _sociallogin(_claims(hd="evil.com", email="x@evil.com"))
            )
        assert exc.value.response.status_code == 403
        assert b"domain_not_allowed" in exc.value.response.content

    def test_pre_social_login_denies_not_allowlisted(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider_raw(allowed_emails=["only@example.com"])]
        with pytest.raises(ImmediateHttpResponse) as exc:
            TapSocialAccountAdapter().pre_social_login(self._request(), _sociallogin(_claims()))
        assert b"account_not_allowlisted" in exc.value.response.content

    def test_pre_social_login_denies_unknown_provider(self, settings):
        settings.TAP_AUTH_PROVIDERS = []  # no config for this provider id
        with pytest.raises(ImmediateHttpResponse):
            TapSocialAccountAdapter().pre_social_login(self._request(), _sociallogin(_claims()))

    def test_pre_social_login_denies_linking_same_email(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider_raw()]
        # an existing user already holds this email
        get_user_model().objects.create_user(username="existing", email="operator@example.com")
        with pytest.raises(ImmediateHttpResponse) as exc:
            TapSocialAccountAdapter().pre_social_login(self._request(), _sociallogin(_claims(), is_existing=False))
        assert b"identity_linking_disabled" in exc.value.response.content

    def test_is_auto_signup_follows_policy(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider_raw(auto_provision=False)]
        assert TapSocialAccountAdapter().is_auto_signup_allowed(self._request(), _sociallogin(_claims())) is False
        settings.TAP_AUTH_PROVIDERS = [_provider_raw(auto_provision=True)]
        assert TapSocialAccountAdapter().is_auto_signup_allowed(self._request(), _sociallogin(_claims())) is True

    def test_social_signup_open_despite_closed_local(self, settings):
        # a permitted Google login must not hit allauth's "Sign Up Closed" just
        # because LOCAL public self-signup is disabled
        from tap_auth.adapter import TapAccountAdapter

        settings.TAP_AUTH_PROVIDERS = [_provider_raw()]
        assert TapSocialAccountAdapter().is_open_for_signup(self._request(), _sociallogin(_claims())) is True
        assert TapAccountAdapter().is_open_for_signup(self._request()) is False  # local stays closed

    def test_sync_external_identity_creates_record(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_provider_raw()]
        user = get_user_model().objects.create_user(username="pending")
        sl = _sociallogin(
            _claims(given_name="George", family_name="Aydlette", picture="https://lh3.googleusercontent.com/p")
        )
        TapSocialAccountAdapter()._sync_external_identity(sl, user)
        ei = ExternalIdentity.objects.get(provider_id=PROVIDER_ID, subject="google-sub-123")
        assert ei.user_id == user.pk
        assert ei.email_snapshot == "operator@example.com"
        assert ei.hosted_domain_snapshot == "example.com"
        assert ei.status == ExternalIdentityStatus.ACTIVE
        user.refresh_from_db()
        assert user.username.startswith(f"ext-{PROVIDER_ID}-")
        assert user.email == "operator@example.com"
        # display profile for the UI (never the generated username)
        assert user.get_full_name() == "George Aydlette"
        assert user.avatar_url == "https://lh3.googleusercontent.com/p"

    def test_apply_initial_grants_grants_all_mapped_roles(self, settings):
        # A single email may be granted several human roles at once.
        settings.TAP_AUTH_INITIAL_GRANTS = {"operator@example.com": ["tap_admin", "tap_viewer"]}
        Group.objects.get_or_create(name="tap_admin")
        Group.objects.get_or_create(name="tap_viewer")
        user = get_user_model().objects.create_user(username="g", email="operator@example.com")
        TapSocialAccountAdapter()._apply_initial_grants(user)
        assert user.groups.filter(name="tap_admin").exists()
        assert user.groups.filter(name="tap_viewer").exists()

    def test_apply_initial_grants_viewer_only(self, settings):
        # The Sam-as-guest path: a non-admin, read-only grant.
        settings.TAP_AUTH_INITIAL_GRANTS = {"sam@example.com": ["tap_viewer"]}
        Group.objects.get_or_create(name="tap_viewer")
        Group.objects.get_or_create(name="tap_admin")
        user = get_user_model().objects.create_user(username="sam", email="sam@example.com")
        TapSocialAccountAdapter()._apply_initial_grants(user)
        assert user.groups.filter(name="tap_viewer").exists()
        assert not user.groups.filter(name="tap_admin").exists()

    def test_apply_initial_grants_skips_unmapped_email(self, settings):
        settings.TAP_AUTH_INITIAL_GRANTS = {"someone@example.com": ["tap_admin"]}
        Group.objects.get_or_create(name="tap_admin")
        user = get_user_model().objects.create_user(username="h", email="other@example.com")
        TapSocialAccountAdapter()._apply_initial_grants(user)
        assert not user.groups.filter(name="tap_admin").exists()

    def test_apply_initial_grants_refuses_non_human_role(self, settings):
        # Defense in depth: even if a program-only role leaks into the map (past
        # the schema/boot guards), the adapter refuses to grant it to a person —
        # a human can NEVER be handed a program actor's authority via login.
        settings.TAP_AUTH_INITIAL_GRANTS = {"x@example.com": ["tap_bootloader", "tap_viewer"]}
        Group.objects.get_or_create(name="tap_bootloader")
        Group.objects.get_or_create(name="tap_viewer")
        user = get_user_model().objects.create_user(username="x", email="x@example.com")
        TapSocialAccountAdapter()._apply_initial_grants(user)
        assert not user.groups.filter(name="tap_bootloader").exists()  # refused
        assert user.groups.filter(name="tap_viewer").exists()  # the grantable one still applied

    def test_apply_initial_grants_is_add_only_idempotent(self, settings):
        # Add-only: never removes a pre-existing membership; idempotent on re-run.
        settings.TAP_AUTH_INITIAL_GRANTS = {"operator@example.com": ["tap_viewer"]}
        Group.objects.get_or_create(name="tap_admin")
        Group.objects.get_or_create(name="tap_viewer")
        user = get_user_model().objects.create_user(username="g2", email="operator@example.com")
        user.groups.add(Group.objects.get(name="tap_admin"))  # a standing grant the map omits
        adapter = TapSocialAccountAdapter()
        adapter._apply_initial_grants(user)
        adapter._apply_initial_grants(user)  # idempotent
        assert user.groups.filter(name="tap_viewer").exists()
        assert user.groups.filter(name="tap_admin").exists()  # NOT revoked by omission


# --------------------------------------------------------------------------- #
# claim un-wrapping — allauth 65 openid_connect stores extra_data WRAPPED
# (regression: a wrapped shape was read at the top level → email_not_verified)
# --------------------------------------------------------------------------- #


class TestClaimUnwrapping:
    def test_wrapped_userinfo_and_id_token_merged(self):
        from tap_auth.adapter import _pick_claims

        wrapped = {
            "userinfo": {"email": "operator@example.com", "name": "George"},
            "id_token": {"email_verified": True, "hd": "example.com", "sub": "s1"},
        }
        c = _pick_claims(wrapped)
        assert c["email"] == "operator@example.com"  # from userinfo
        assert c["email_verified"] is True  # from id_token
        assert c["hd"] == "example.com"

    def test_id_token_wins_on_overlap(self):
        # the SIGNED id_token is authoritative for security claims; a userinfo
        # value must never widen access past the id_token's hd
        from tap_auth.adapter import _pick_claims

        c = _pick_claims({"userinfo": {"hd": "spoof.com"}, "id_token": {"hd": "real.com"}})
        assert c["hd"] == "real.com"

    def test_flat_extra_data_passthrough(self):
        from tap_auth.adapter import _pick_claims

        assert _pick_claims({"email": "a@b.com"})["email"] == "a@b.com"

    def test_non_dict_is_empty(self):
        from tap_auth.adapter import _pick_claims

        assert _pick_claims(None) == {}

    @pytest.mark.django_db
    def test_pre_social_login_allows_wrapped_verified(self, settings):
        # the end-to-end regression: a real-shaped (wrapped) Google response for a
        # verified Workspace account must be ALLOWED, not denied email_not_verified
        from django.test import RequestFactory

        settings.TAP_AUTH_PROVIDERS = [_provider_raw(allowed_emails=["operator@example.com"])]
        account = SocialAccount(
            provider=PROVIDER_ID,
            uid="s1",
            extra_data={
                "userinfo": {"email": "operator@example.com", "name": "George", "sub": "s1"},
                "id_token": {"email_verified": True, "hd": "example.com", "sub": "s1"},
            },
        )
        sl = SocialLogin(account=account)
        sl.user = get_user_model()(username="pending")
        sl.account.pk = None
        # must NOT raise
        TapSocialAccountAdapter().pre_social_login(RequestFactory().get("/cb"), sl)


@pytest.mark.django_db
class TestUserDisplay:
    """req-tap-auth-external-identity — UI shows email, not the generated username."""

    def test_prefers_email_over_generated_username(self):
        from tap_auth.adapter import user_display

        u = get_user_model().objects.create_user(username="ext-example-google-abc123", email="operator@example.com")
        assert user_display(u) == "operator@example.com"

    def test_falls_back_to_username_without_email(self):
        from tap_auth.adapter import user_display

        u = get_user_model().objects.create_user(username="localadmin", email="")
        assert user_display(u) == "localadmin"


# --------------------------------------------------------------------------- #
# The initial-grant escalation path, end to end through save_user
# --------------------------------------------------------------------------- #

GITHUB_PROVIDER_ID = "acme-github"


def _github_provider_raw(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": GITHUB_PROVIDER_ID,
        "type": "github_oauth",
        "display_name": "Acme (GitHub)",
        "allowed_user_ids": [583231],
    }
    raw.update(over)
    return raw


def _github_sociallogin(claims: dict[str, Any]) -> SocialLogin:
    account = SocialAccount(provider=GITHUB_PROVIDER_ID, uid=str(claims["id"]), extra_data=claims)
    sl = SocialLogin(account=account)
    sl.user = get_user_model()(username="pending", email=claims.get("email", ""))
    sl.state = {}
    sl.account.pk = None
    sl.email_addresses = []  # GitHub asserted NO verified address
    return sl


@pytest.mark.django_db
class TestInitialGrantOrdering:
    """`save_user` clears the self-asserted email BEFORE the grant map is read.

    The ordering is the whole control. `DefaultSocialAccountAdapter.populate_user`
    — which TAP does not override — has already written the provider's
    self-asserted email onto the user by the time `save_user` runs, and
    `TAP_AUTH_INITIAL_GRANTS` is keyed by `User.email`. If grants were applied
    before `_sync_external_identity` cleared that field, an allowlisted GitHub
    account could name any initial-admin address in its own editable profile and
    be handed the role. Nothing else in the suite pins the order, so a refactor
    that swapped the two calls would reopen it silently.
    """

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_self_asserted_email_cannot_earn_an_initial_grant(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_github_provider_raw()]
        settings.TAP_AUTH_INITIAL_GRANTS = {"admin@example.com": ["tap_admin"]}
        Group.objects.get_or_create(name="tap_admin")

        # An allowlisted account whose GITHUB PROFILE claims the initial-admin
        # address. GitHub never verified it — the account holder typed it in.
        sl = _github_sociallogin({"id": 583231, "login": "octocat", "email": "admin@example.com"})
        adapter = TapSocialAccountAdapter()
        user = get_user_model().objects.create_user(username="pending-gh", email="admin@example.com")

        adapter._sync_external_identity(sl, user)
        adapter._apply_initial_grants(user)

        user.refresh_from_db()
        assert user.email == ""  # the unverified address was CLEARED, not preserved
        assert not user.groups.filter(name="tap_admin").exists()

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_save_user_syncs_the_identity_before_reading_the_grant_map(self, settings):
        """The ordering itself, asserted at `save_user` rather than inferred.

        Recording the call sequence is the point: it fails if the two lines are
        ever swapped, which is the mutation that reopens the escalation, and it
        does not depend on allauth's signup machinery to reach the assertion.
        """
        calls: list[str] = []
        adapter = TapSocialAccountAdapter()
        user = get_user_model().objects.create_user(username="ordering", email="admin@example.com")

        def _record_sync(sociallogin, u):
            calls.append("sync")

        def _record_grants(u):
            calls.append("grants")

        monkey = pytest.MonkeyPatch()
        try:
            monkey.setattr(type(adapter), "save_user", TapSocialAccountAdapter.save_user)
            monkey.setattr(adapter, "_sync_external_identity", _record_sync)
            monkey.setattr(adapter, "_apply_initial_grants", _record_grants)
            monkey.setattr(type(adapter).__mro__[1], "save_user", lambda self, request, sociallogin, form=None: user)
            sl = _github_sociallogin({"id": 583231, "login": "octocat", "email": "admin@example.com"})
            adapter.save_user(RequestFactory().get("/auth/github/login/callback/"), sl)
        finally:
            monkey.undo()

        assert calls == ["sync", "grants"], "the identity sync must clear User.email before grants are read"


@pytest.mark.django_db
class TestOwnerGrant:
    """`_apply_owner_grant` — the instance owner gets a role keyed on (provider, uid).

    The gap this closes, observed 2026-09-22 on a live Codespace: every derived value was
    correct, `owner_only` admitted exactly the right person, and that person then got
    `Forbidden (capability_denied)` — because grants key on email and a Codespace cannot know
    the visitor's email in advance (`codespace_demo`'s own description says so).
    """

    class _Acct:
        def __init__(self, uid: str, provider: str = "demo-github") -> None:
            self.uid = uid
            self.provider = provider

    class _Login:
        def __init__(self, uid: str) -> None:
            self.account = TestOwnerGrant._Acct(uid)

    def _user(self, name: str = "owner"):
        return get_user_model().objects.create_user(username=name, email="")

    def test_owner_uid_match_grants_the_role(self, settings):
        settings.TAP_AUTH_OWNER_ROLE = "tap_admin"
        settings.TAP_AUTH_INSTANCE_OWNER = {"login": "notgeorge", "user_id": "286052"}
        Group.objects.get_or_create(name="tap_admin")
        user = self._user()
        TapSocialAccountAdapter()._apply_owner_grant(self._Login("286052"), user)
        assert user.groups.filter(name="tap_admin").exists()

    def test_grants_with_NO_email_at_all(self, settings):
        # The whole point. The sibling email path returns early on a falsy email; this one
        # must not, because the Codespace owner may legitimately have no verified address.
        settings.TAP_AUTH_OWNER_ROLE = "tap_admin"
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": "286052"}
        Group.objects.get_or_create(name="tap_admin")
        user = self._user()
        assert not user.email
        TapSocialAccountAdapter()._apply_owner_grant(self._Login("286052"), user)
        assert user.groups.filter(name="tap_admin").exists()

    def test_non_owner_uid_gets_nothing(self, settings):
        settings.TAP_AUTH_OWNER_ROLE = "tap_admin"
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": "286052"}
        Group.objects.get_or_create(name="tap_admin")
        user = self._user("stranger")
        TapSocialAccountAdapter()._apply_owner_grant(self._Login("999999"), user)
        assert not user.groups.filter(name="tap_admin").exists()

    def test_OFF_by_default(self, settings):
        # An install that sets nothing must see no change — this cannot hand out a role by
        # existing. The owner matches; the feature is simply not enabled.
        settings.TAP_AUTH_OWNER_ROLE = ""
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": "286052"}
        Group.objects.get_or_create(name="tap_admin")
        user = self._user()
        TapSocialAccountAdapter()._apply_owner_grant(self._Login("286052"), user)
        assert not user.groups.filter(name="tap_admin").exists()

    def test_unresolved_owner_grants_nothing(self, settings):
        # `evaluate_access` denies on an unresolved owner; granting here would be the
        # mirror-image fail-open of that refusal. An empty owner is "nobody", never "anybody".
        settings.TAP_AUTH_OWNER_ROLE = "tap_admin"
        settings.TAP_AUTH_INSTANCE_OWNER = {}
        Group.objects.get_or_create(name="tap_admin")
        user = self._user()
        TapSocialAccountAdapter()._apply_owner_grant(self._Login(""), user)
        assert not user.groups.filter(name="tap_admin").exists()

    def test_refuses_a_non_human_grantable_role(self, settings):
        # Same guarantee the email path carries: this can never give a person a program
        # actor's authority, even if the role name is set by an operator.
        settings.TAP_AUTH_OWNER_ROLE = "tap_bootloader"
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": "286052"}
        Group.objects.get_or_create(name="tap_bootloader")
        user = self._user()
        TapSocialAccountAdapter()._apply_owner_grant(self._Login("286052"), user)
        assert not user.groups.filter(name="tap_bootloader").exists()
