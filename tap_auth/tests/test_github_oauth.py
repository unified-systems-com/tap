"""GitHub OAuth provider tests (req-tap-auth-github-oauth).

The cred-independent layers: config validation, the pure access decision, the
allauth settings shape asserted against what the INSTALLED allauth package
actually consumes, and the live self-test with a mocked token endpoint. An
end-to-end login against real GitHub needs an OAuth App and is a manual smoke.

The negative tests are the point. A test that only proves an allowlisted login is
admitted passes for the wrong reason — it would pass against a provider with no
gate at all.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import requests

from tap.secret_naming import SECRET_SUFFIX
from tap_auth.boot import _FRAGMENT_PATH as _SCHEMA_PATH
from tap_auth.providers import (
    ProviderConfig,
    SelfTestPhase,
    SelfTestResult,
    SelfTestStatus,
    build_socialaccount_providers,
    get_provider,
    provider_types,
)
from tap_auth.providers.base import VERIFIED_EMAILS_CLAIM, AccessDecision, ProviderError
from tap_auth.providers.github_oauth import (
    ALLAUTH_PROVIDER,
    CALLBACK_PATH,
    PROVIDER_TYPE,
    GitHubOAuthProvider,
)

PROVIDER_ID = "acme-github"

# A GitHub account the policy admits, and one it does not. Both are shaped like a
# real `/user` response (the body allauth stores as extra_data).
ALLOWED_ID = "583231"
ALLOWED_LOGIN = "octocat"
OUTSIDER_ID = "999001"
OUTSIDER_LOGIN = "mallory"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _write_secret(root: Path, key: str = PROVIDER_ID, **overrides: object) -> Path:
    doc: dict[str, Any] = {
        "scope": "auth",
        "key": key,
        "kind": "oauth2_client",
        "description": "test github oauth client",
        "data": {"client_id": "Ov23liTESTCLIENTID", "client_secret": "not-a-real-value"},
    }
    doc.update(overrides)
    path = root / f"{key}{SECRET_SUFFIX}"
    path.write_text(json.dumps(doc))
    return path


def _raw(**over: object) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": PROVIDER_ID,
        "type": PROVIDER_TYPE,
        "display_name": "ACME (GitHub)",
        "allowed_user_ids": [int(ALLOWED_ID)],
    }
    raw.update(over)
    return raw


def _cfg(**over) -> ProviderConfig:
    return ProviderConfig.from_dict(_raw(**over))


def _claims(**over: object) -> dict[str, Any]:
    """A GitHub `/user` body as allauth stores it. Note what is NOT here: `emails`
    (allauth strips it) and any verification flag — that is the whole point."""
    c: dict[str, Any] = {
        "id": int(ALLOWED_ID),
        "login": ALLOWED_LOGIN,
        "name": "The Octocat",
        "email": "octocat@example.com",  # SELF-ASSERTED. Never trusted.
        "avatar_url": "https://avatars.githubusercontent.com/u/583231",
        "html_url": "https://github.com/octocat",
    }
    c.update(over)
    return c


def _decide(raw: dict[str, Any], claims: dict[str, Any]) -> AccessDecision:
    cfg = ProviderConfig.from_dict(raw)
    return get_provider(cfg.type).evaluate_access(cfg, claims)


def _by_check(results: Iterable[SelfTestResult]) -> dict[str, SelfTestResult]:
    return {r.check: r for r in results}


def _mock_response(status: int, payload: dict[str, Any] | None) -> mock.Mock:
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    return resp


# --------------------------------------------------------------------------- #
# registry — the seam this provider exists to prove
# --------------------------------------------------------------------------- #


class TestRegistry:
    @pytest.mark.spec("req-tap-auth-github-oauth-1")
    def test_registered_as_a_second_type(self):
        assert PROVIDER_TYPE in provider_types()
        assert "google_oidc" in provider_types()  # the first one is still there
        assert get_provider(PROVIDER_TYPE).type == PROVIDER_TYPE

    @pytest.mark.spec("req-tap-auth-github-oauth-1")
    def test_declares_the_github_allauth_engine_not_oidc(self):
        # The fact the wiring used to hardcode. Filing a GitHub app under
        # openid_connect would hand it to allauth's OIDC engine, which reads
        # app.settings["server_url"].
        assert get_provider(PROVIDER_TYPE).allauth_provider == "github"
        assert get_provider("google_oidc").allauth_provider == "openid_connect"


# --------------------------------------------------------------------------- #
# evaluate_access — the security core, pure and claim-only
# --------------------------------------------------------------------------- #


class TestEvaluateAccess:
    # -- the negative cases, first --------------------------------------- #

    @pytest.mark.spec("req-tap-auth-github-oauth-4")
    def test_deny_account_outside_the_id_allowlist(self):
        d = _decide(_raw(), _claims(id=int(OUTSIDER_ID), login=OUTSIDER_LOGIN))
        assert d.allowed is False
        assert d.reason == "account_not_allowlisted"
        assert OUTSIDER_ID in d.log_detail

    @pytest.mark.spec("req-tap-auth-github-oauth-3")
    def test_a_login_allowlist_admits_nobody(self):
        """The recycled-handle bypass, inverted. This configuration returned
        allowed=True for a DIFFERENT numeric account that presented the allowlisted
        handle. There is no allowlist-by-login now, so the stale key is inert — the
        policy is empty and the account is refused."""
        raw = _raw(allowed_user_ids=[], allowed_logins=[ALLOWED_LOGIN])
        d = _decide(raw, _claims(id=int(OUTSIDER_ID), login=ALLOWED_LOGIN))
        assert d.allowed is False and d.reason == "account_not_allowlisted"
        # The clause vocabulary itself, so a reintroduced login clause fails here too.
        assert d.matched_rule == "allowed_user_ids,owner_only"

    @pytest.mark.spec("req-tap-auth-github-oauth-3")
    def test_a_stale_allowed_logins_key_is_refused_by_the_schema(self):
        """Inert is not enough on its own: a key the provider ignores is the
        presence-not-correctness shape — an operator reads their own config as a
        policy that is enforced. The boot schema refuses the provider entry outright
        (`additionalProperties: false`), so a stale allowlist cannot boot quietly."""
        schema = json.loads(_SCHEMA_PATH.read_text())
        item = schema["properties"]["providers"]["items"]
        assert item["additionalProperties"] is False
        assert "allowed_logins" not in item["properties"]

    @pytest.mark.spec("req-tap-auth-github-oauth-2")
    def test_deny_when_an_allowlisted_login_arrives_on_a_different_account(self):
        """The recycled-handle case. `octocat` is allowlisted BY ID; someone who
        later registers that handle presents the same login and a different id,
        and must not inherit the identity."""
        raw = _raw(allowed_user_ids=[int(ALLOWED_ID)])
        d = _decide(raw, _claims(id=int(OUTSIDER_ID), login=ALLOWED_LOGIN))
        assert d.allowed is False and d.reason == "account_not_allowlisted"

    @pytest.mark.spec("req-tap-auth-github-oauth-2")
    def test_deny_when_no_numeric_id_is_returned(self):
        d = _decide(_raw(), _claims(id=None))
        assert d.allowed is False and d.reason == "subject_unusable"

    @pytest.mark.spec("req-tap-auth-github-oauth-2")
    def test_a_login_string_in_the_id_position_is_not_a_subject(self):
        # Fails closed rather than silently keying identity on a renameable value.
        d = _decide(_raw(), _claims(id=ALLOWED_LOGIN))
        assert d.allowed is False and d.reason == "subject_unusable"

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_deny_when_owner_only_cannot_resolve_an_owner(self, settings):
        settings.TAP_AUTH_INSTANCE_OWNER = {}
        raw = _raw(allowed_user_ids=[], owner_only=True)
        d = _decide(raw, _claims())
        assert d.allowed is False
        assert d.reason == "policy_unresolvable"  # NOT an allow, and not a generic refusal

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_owner_only_denies_an_id_mismatch_even_when_the_login_matches(self, settings):
        """The owner clause combined its id and login tests with OR, so a numeric-id
        MISMATCH was ignored whenever the handle matched: whoever re-registered a
        released owner login became the owner. The id is now the only comparison."""
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": ALLOWED_ID, "login": ALLOWED_LOGIN}
        raw = _raw(allowed_user_ids=[], owner_only=True)
        d = _decide(raw, _claims(id=int(OUTSIDER_ID), login=ALLOWED_LOGIN))
        assert d.allowed is False and d.reason == "account_not_allowlisted"

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_owner_only_denies_an_owner_known_only_by_login(self, settings):
        """A login is not an owner. With no numeric id there is nothing durable to
        compare, so the clause is unresolvable rather than login-matched — and says
        so with its own reason code instead of a generic refusal."""
        settings.TAP_AUTH_INSTANCE_OWNER = {"login": ALLOWED_LOGIN}
        raw = _raw(allowed_user_ids=[], owner_only=True)
        d = _decide(raw, _claims(id=int(ALLOWED_ID), login=ALLOWED_LOGIN))
        assert d.allowed is False and d.reason == "policy_unresolvable"

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_owner_only_denies_a_non_owner(self, settings):
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": ALLOWED_ID}
        raw = _raw(allowed_user_ids=[], owner_only=True)
        d = _decide(raw, _claims(id=int(OUTSIDER_ID), login=OUTSIDER_LOGIN))
        assert d.allowed is False and d.reason == "account_not_allowlisted"

    # -- the positive cases ---------------------------------------------- #

    @pytest.mark.spec("req-tap-auth-github-oauth-4")
    def test_allow_by_user_id(self):
        d = _decide(_raw(), _claims())
        assert d.allowed is True and d.matched_rule == "allowed_user_ids"

    @pytest.mark.spec("req-tap-auth-github-oauth-2")
    def test_allow_by_user_id_survives_a_login_rename(self):
        # Same account, new handle: the id clause still matches.
        d = _decide(_raw(), _claims(login="octocat-renamed"))
        assert d.allowed is True and d.matched_rule == "allowed_user_ids"

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_allow_the_derived_owner_by_id(self, settings):
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": ALLOWED_ID, "login": ALLOWED_LOGIN}
        raw = _raw(allowed_user_ids=[], owner_only=True)
        d = _decide(raw, _claims())
        assert d.allowed is True and d.matched_rule == "owner_only"

    # -- verified email ---------------------------------------------------- #

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_self_asserted_profile_email_is_never_the_verified_email(self):
        d = _decide(_raw(), _claims(email="admin@example.com"))
        assert d.allowed is True
        assert d.verified_email == ""  # the /user email carries no verification

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_verified_email_comes_from_the_injected_verified_set(self):
        claims = _claims(email="typed-in@example.com")
        claims[VERIFIED_EMAILS_CLAIM] = ["real@example.com", "other@example.com"]
        d = _decide(_raw(), claims)
        assert d.verified_email == "real@example.com"

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_a_missing_verified_email_does_not_block_an_allowlisted_account(self):
        # Re-expressed, not dropped: the policy is id-based, so an account with no
        # verified address is still admitted — it just yields no trusted email.
        d = _decide(_raw(), _claims(email=None))
        assert d.allowed is True and d.verified_email == ""


# --------------------------------------------------------------------------- #
# profile snapshot
# --------------------------------------------------------------------------- #


class TestProfileSnapshot:
    def test_reads_githubs_own_vocabulary(self):
        p = GitHubOAuthProvider().profile_snapshot(_cfg(), _claims())
        assert p.display_name == "The Octocat"
        assert p.avatar_url == "https://avatars.githubusercontent.com/u/583231"
        # GitHub has one free-text name; TAP does not guess a given/family split.
        assert p.first_name == "" and p.last_name == ""
        assert p.hosted_domain == ""

    def test_falls_back_to_the_login_when_no_name_is_set(self):
        p = GitHubOAuthProvider().profile_snapshot(_cfg(), _claims(name=None))
        assert p.display_name == ALLOWED_LOGIN


# --------------------------------------------------------------------------- #
# validate_config
# --------------------------------------------------------------------------- #


class TestValidateConfig:
    @pytest.fixture(autouse=True)
    def _base_url(self, settings):
        settings.TAP_BASE_URL = "https://tap.example.com"
        settings.TAP_AUTH_PROVIDERS = []
        settings.TAP_AUTH_INSTANCE_OWNER = {}

    @pytest.mark.spec("req-tap-auth-github-oauth-3")
    def test_no_policy_fails(self):
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg(allowed_user_ids=[])))
        assert results["access_policy"].status is SelfTestStatus.FAIL

    @pytest.mark.spec("req-tap-auth-github-oauth-3")
    def test_a_policy_passes(self):
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg()))
        assert results["access_policy"].status is SelfTestStatus.PASS

    @pytest.mark.spec("req-tap-auth-github-oauth-3")
    def test_non_numeric_user_id_entry_fails_rather_than_being_dropped(self):
        # A login typed into allowed_user_ids matches nothing. Silently dropping it
        # would leave an operator believing a policy is enforced that is not.
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg(allowed_user_ids=["octocat"])))
        assert results["allowed_user_ids"].status is SelfTestStatus.FAIL

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_owner_only_without_a_resolvable_owner_fails(self, settings):
        settings.TAP_AUTH_INSTANCE_OWNER = {}
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg(allowed_user_ids=[], owner_only=True)))
        assert results["owner_only"].status is SelfTestStatus.FAIL

    @pytest.mark.spec("req-tap-auth-github-oauth-5")
    def test_owner_only_with_a_resolvable_owner_passes(self, settings):
        settings.TAP_AUTH_INSTANCE_OWNER = {"user_id": ALLOWED_ID}
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg(allowed_user_ids=[], owner_only=True)))
        assert results["owner_only"].status is SelfTestStatus.PASS

    @pytest.mark.spec("req-tap-auth-github-oauth-9")
    def test_a_second_github_provider_fails(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_raw(), _raw(id="other-github")]
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg()))
        assert results["single_github_provider"].status is SelfTestStatus.FAIL
        assert "other-github" in results["single_github_provider"].message

    @pytest.mark.spec("req-tap-auth-github-oauth-9")
    def test_one_github_provider_passes(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_raw()]
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg()))
        assert results["single_github_provider"].status is SelfTestStatus.PASS

    def test_callback_url_is_the_fixed_oauth2_route(self):
        assert GitHubOAuthProvider().callback_url(_cfg()) == f"https://tap.example.com{CALLBACK_PATH}"

    def test_missing_base_url_fails(self, settings):
        settings.TAP_BASE_URL = ""
        results = _by_check(GitHubOAuthProvider().validate_config(_cfg()))
        assert results["tap_base_url"].status is SelfTestStatus.FAIL

    def test_wrong_type_fails_fast(self):
        cfg = ProviderConfig.from_dict({"id": "p", "type": "google_oidc", "display_name": "P"})
        results = GitHubOAuthProvider().validate_config(cfg)
        assert results[0].check == "type" and results[0].status is SelfTestStatus.FAIL


# --------------------------------------------------------------------------- #
# self-test: secret + the live credential adjudication
# --------------------------------------------------------------------------- #


class TestSelfTest:
    @pytest.fixture(autouse=True)
    def _base(self, settings, tmp_path):
        settings.TAP_BASE_URL = "https://tap.example.com"
        settings.TAP_AUTH_PROVIDERS = []
        settings.TAP_AUTH_INSTANCE_OWNER = {}
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        self.root = tmp_path

    def test_missing_secret_fails_offline(self):
        results = _by_check(GitHubOAuthProvider().self_test(_cfg(), {}, live=False))
        assert results["secret"].status is SelfTestStatus.FAIL

    def test_present_secret_passes_offline(self):
        _write_secret(self.root)
        provider = GitHubOAuthProvider()
        cfg = _cfg()
        results = _by_check(provider.self_test(cfg, provider.resolve_secrets(cfg), live=False))
        assert results["secret"].status is SelfTestStatus.PASS

    def test_resolve_secret_accepts_the_oauth2_client_kind(self):
        _write_secret(self.root)
        data = GitHubOAuthProvider().resolve_secrets(_cfg())
        assert data["client_id"] == "Ov23liTESTCLIENTID"

    def test_resolve_secret_rejects_a_foreign_kind(self):
        _write_secret(self.root, kind="github_pat")
        with pytest.raises(ProviderError, match="oauth client schema"):
            GitHubOAuthProvider().resolve_secrets(_cfg())

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_off_skips_the_credential_check(self):
        _write_secret(self.root)
        provider = GitHubOAuthProvider()
        cfg = _cfg()
        result = _by_check(provider.self_test(cfg, provider.resolve_secrets(cfg), live=False))["client_credentials"]
        assert result.status is SelfTestStatus.SKIP
        assert result.phase is SelfTestPhase.LIVE

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_bad_verification_code_is_the_pass_signal(self):
        secrets = {"client_id": "cid", "client_secret": "sec"}
        with mock.patch(
            "tap_auth.providers.github_oauth.requests.post",
            return_value=_mock_response(200, {"error": "bad_verification_code"}),
        ):
            result = GitHubOAuthProvider()._credentials_check(secrets, live=True)
        assert result.status is SelfTestStatus.PASS

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_incorrect_client_credentials_fails(self):
        secrets = {"client_id": "cid", "client_secret": "wrong"}
        with mock.patch(
            "tap_auth.providers.github_oauth.requests.post",
            return_value=_mock_response(200, {"error": "incorrect_client_credentials"}),
        ):
            result = GitHubOAuthProvider()._credentials_check(secrets, live=True)
        assert result.status is SelfTestStatus.FAIL

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_unknown_client_id_404_fails(self):
        secrets = {"client_id": "nope", "client_secret": "sec"}
        with mock.patch(
            "tap_auth.providers.github_oauth.requests.post",
            return_value=_mock_response(404, {"error": "Not Found"}),
        ):
            result = GitHubOAuthProvider()._credentials_check(secrets, live=True)
        assert result.status is SelfTestStatus.FAIL

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_unrecognised_answer_warns_rather_than_passing(self):
        # The false-green guard: an answer we do not understand is not health.
        secrets = {"client_id": "cid", "client_secret": "sec"}
        with mock.patch(
            "tap_auth.providers.github_oauth.requests.post",
            return_value=_mock_response(200, {"error": "something_new"}),
        ):
            result = GitHubOAuthProvider()._credentials_check(secrets, live=True)
        assert result.status is SelfTestStatus.WARN
        assert "something_new" in result.message

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_network_failure_fails(self):
        secrets = {"client_id": "cid", "client_secret": "sec"}
        with mock.patch(
            "tap_auth.providers.github_oauth.requests.post",
            side_effect=requests.RequestException("boom"),
        ):
            result = GitHubOAuthProvider()._credentials_check(secrets, live=True)
        assert result.status is SelfTestStatus.FAIL

    @pytest.mark.spec("req-tap-auth-github-oauth-7")
    def test_live_probe_never_sends_a_plausible_code(self):
        secrets = {"client_id": "cid", "client_secret": "sec"}
        with mock.patch(
            "tap_auth.providers.github_oauth.requests.post",
            return_value=_mock_response(200, {"error": "bad_verification_code"}),
        ) as post:
            GitHubOAuthProvider()._credentials_check(secrets, live=True)
        sent = post.call_args.kwargs["data"]
        assert sent["code"].startswith("tap-auth-selftest")
        assert post.call_args.kwargs["headers"]["Accept"] == "application/json"


# --------------------------------------------------------------------------- #
# allauth settings — asserted against the INSTALLED package's expectations
# --------------------------------------------------------------------------- #


class TestAllauthSettings:
    @pytest.mark.spec("req-tap-auth-github-oauth-8")
    def test_entry_keys_are_exactly_what_allauth_consumes(self, tmp_path, settings):
        """allauth's `_build_apps_from_settings` copies a fixed field list onto a
        SocialApp and ignores everything else; an entry carrying an unrecognised key
        would look configured and do nothing. Read the field list off the installed
        package rather than restating it here."""
        import inspect

        from allauth.socialaccount import adapter as allauth_adapter

        source = inspect.getsource(allauth_adapter._build_apps_from_settings)
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path)
        provider = GitHubOAuthProvider()
        cfg = _cfg()
        entry = provider.build_allauth_settings(cfg, provider.resolve_secrets(cfg))
        for key in entry:
            assert f'"{key}"' in source, f"allauth's app builder ignores the key {key!r}"

    @pytest.mark.django_db
    @pytest.mark.spec("req-tap-auth-github-oauth-8")
    def test_entry_is_accepted_by_the_installed_github_provider(self, tmp_path, settings):
        """End of the shape question: hand the built entry to allauth exactly as
        settings would, and confirm allauth constructs its GitHub provider from it
        with the TAP provider id as `sub_id` — the value SocialAccount.provider is
        stamped with, and therefore the key the social adapter looks the policy up by."""
        from allauth.socialaccount.adapter import get_adapter
        from allauth.socialaccount.providers.github.provider import GitHubProvider

        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path)
        settings.SOCIALACCOUNT_PROVIDERS = build_socialaccount_providers([_raw()])

        app = get_adapter().get_app(None, provider=PROVIDER_ID)
        assert app.provider == ALLAUTH_PROVIDER
        assert app.provider_id == PROVIDER_ID
        assert GitHubProvider(request=None, app=app).sub_id == PROVIDER_ID

    @pytest.mark.spec("req-tap-auth-github-oauth-1")
    def test_grouped_under_the_github_engine_not_openid_connect(self, tmp_path, settings):
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path)
        out = build_socialaccount_providers([_raw()])
        assert set(out) == {"github"}
        assert out["github"]["APPS"][0]["provider_id"] == PROVIDER_ID

    @pytest.mark.spec("req-tap-auth-github-oauth-1")
    def test_two_provider_types_produce_two_engine_groups(self, tmp_path, settings):
        """The regression the hardcoded grouping key would have caused: a mixed
        deployment must file each provider under its own allauth engine."""
        settings.TAP_SECRETS_ROOT = str(tmp_path)
        _write_secret(tmp_path)
        _write_secret(tmp_path, key="example-google", kind="oidc_client")
        google = {
            "id": "example-google",
            "type": "google_oidc",
            "display_name": "example.com",
            "allowed_domains": ["example.com"],
        }
        out = build_socialaccount_providers([google, _raw()])
        assert set(out) == {"openid_connect", "github"}
        assert out["openid_connect"]["APPS"][0]["provider_id"] == "example-google"
        assert out["github"]["APPS"][0]["provider_id"] == PROVIDER_ID

    def test_unresolved_secret_raises(self):
        """Both halves must be present for a redirect-flow entry, and the refusal now
        says WHICH is missing — device flow made the two cases distinguishable."""
        provider = GitHubOAuthProvider()
        with pytest.raises(ProviderError, match="client_id not resolved"):
            provider.build_allauth_settings(_cfg(), {})
        with pytest.raises(ProviderError, match="secret not resolved"):
            provider.build_allauth_settings(_cfg(), {"client_id": "x"})


# --------------------------------------------------------------------------- #
# the social adapter, driven with GitHub-shaped data
#
# These are the tests that prove the two decisions with teeth: identity survives a
# rename, and no unverified address ever reaches User.email.
# --------------------------------------------------------------------------- #


def _sociallogin(claims: dict[str, Any], *, verified_emails: tuple[str, ...] = ()) -> Any:
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount, SocialLogin
    from django.contrib.auth import get_user_model

    account = SocialAccount(provider=PROVIDER_ID, uid=str(claims["id"]), extra_data=claims)
    sl = SocialLogin(account=account)
    sl.user = get_user_model()(username="pending")
    sl.state = {}
    sl.account.pk = None
    # allauth populates this from /user/emails; TAP never fabricates verification.
    sl.email_addresses = [EmailAddress(email=e, primary=(i == 0), verified=True) for i, e in enumerate(verified_emails)]
    return sl


@pytest.mark.django_db
class TestAdapterWithGitHub:
    @pytest.fixture(autouse=True)
    def _configured(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_raw()]
        settings.TAP_AUTH_INSTANCE_OWNER = {}
        settings.TAP_AUTH_INITIAL_GRANTS = {}

    @pytest.mark.spec("req-tap-auth-github-oauth-2")
    def test_a_login_rename_does_not_create_a_second_external_identity(self):
        """The rename proof. Same numeric id, different login, twice — one row."""
        from django.contrib.auth import get_user_model

        from tap_auth.adapter import TapSocialAccountAdapter
        from tap_auth.models import ExternalIdentity

        adapter = TapSocialAccountAdapter()
        user = get_user_model().objects.create_user(username="pending")

        adapter._sync_external_identity(_sociallogin(_claims(login="octocat")), user)
        adapter._sync_external_identity(_sociallogin(_claims(login="octocat-renamed")), user)

        rows = ExternalIdentity.objects.filter(provider_id=PROVIDER_ID)
        assert rows.count() == 1
        assert rows.get().subject == ALLOWED_ID  # the numeric id, not either login

    @pytest.mark.spec("req-tap-auth-github-oauth-2")
    def test_a_different_account_is_a_different_identity(self):
        """The other half: two real accounts must never collapse into one row, even
        if a handle moves between them."""
        from django.contrib.auth import get_user_model

        from tap_auth.adapter import TapSocialAccountAdapter
        from tap_auth.models import ExternalIdentity

        adapter = TapSocialAccountAdapter()
        first = get_user_model().objects.create_user(username="first")
        second = get_user_model().objects.create_user(username="second")

        adapter._sync_external_identity(_sociallogin(_claims()), first)
        adapter._sync_external_identity(_sociallogin(_claims(id=int(OUTSIDER_ID), login=ALLOWED_LOGIN)), second)

        assert ExternalIdentity.objects.filter(provider_id=PROVIDER_ID).count() == 2

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_a_self_asserted_email_never_reaches_the_user(self):
        """The privilege-escalation guard. `User.email` keys TAP_AUTH_INITIAL_GRANTS,
        so an address GitHub never verified must not land on the user — even though
        the account itself is allowlisted and the login succeeds."""
        from django.contrib.auth import get_user_model

        from tap_auth.adapter import TapSocialAccountAdapter
        from tap_auth.models import ExternalIdentity

        user = get_user_model().objects.create_user(username="pending")
        sl = _sociallogin(_claims(email="admin@example.com"))  # typed in, unverified
        TapSocialAccountAdapter()._sync_external_identity(sl, user)

        user.refresh_from_db()
        assert user.email == ""
        assert ExternalIdentity.objects.get(provider_id=PROVIDER_ID).email_snapshot == ""

    @pytest.mark.spec("req-tap-auth-github-oauth-6")
    def test_a_github_verified_email_does_reach_the_user(self):
        from django.contrib.auth import get_user_model

        from tap_auth.adapter import TapSocialAccountAdapter

        user = get_user_model().objects.create_user(username="pending")
        sl = _sociallogin(_claims(email="typed-in@example.com"), verified_emails=("real@example.com",))
        TapSocialAccountAdapter()._sync_external_identity(sl, user)

        user.refresh_from_db()
        assert user.email == "real@example.com"

    def test_github_profile_fields_land_on_the_user(self):
        """Before profile_snapshot, a GitHub login produced a user with no name and
        no avatar because the adapter read Google's claim names."""
        from django.contrib.auth import get_user_model

        from tap_auth.adapter import TapSocialAccountAdapter
        from tap_auth.models import ExternalIdentity

        user = get_user_model().objects.create_user(username="pending")
        TapSocialAccountAdapter()._sync_external_identity(_sociallogin(_claims()), user)

        user.refresh_from_db()
        assert user.avatar_url == "https://avatars.githubusercontent.com/u/583231"
        assert ExternalIdentity.objects.get(provider_id=PROVIDER_ID).display_name_snapshot == "The Octocat"

    @pytest.mark.spec("req-tap-auth-github-oauth-4")
    def test_pre_social_login_denies_an_account_outside_the_policy(self):
        """The negative test at the chokepoint, not just in the pure function: an
        outsider is stopped with a 403 before any user exists."""
        from allauth.core.exceptions import ImmediateHttpResponse
        from django.test import RequestFactory

        from tap_auth.adapter import TapSocialAccountAdapter

        request = RequestFactory().get(CALLBACK_PATH)
        sl = _sociallogin(_claims(id=int(OUTSIDER_ID), login=OUTSIDER_LOGIN))
        with pytest.raises(ImmediateHttpResponse) as exc:
            TapSocialAccountAdapter().pre_social_login(request, sl)
        assert exc.value.response.status_code == 403
        assert b"account_not_allowlisted" in exc.value.response.content

    @pytest.mark.spec("req-tap-auth-github-oauth-4")
    def test_pre_social_login_admits_an_allowlisted_account(self):
        from django.test import RequestFactory

        from tap_auth.adapter import TapSocialAccountAdapter

        request = RequestFactory().get(CALLBACK_PATH)
        # no raise == admitted
        TapSocialAccountAdapter().pre_social_login(request, _sociallogin(_claims()))


# --------------------------------------------------------------------------- #
# Device flow: a public client, no secret to resolve
# --------------------------------------------------------------------------- #


def _device_raw(**over: Any) -> dict[str, Any]:
    raw = _raw(**over)
    raw["device_flow"] = True
    raw["client_id"] = "Ov23liEXAMPLE"
    return raw


class TestDeviceFlowConfig:
    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_a_device_entry_resolves_its_public_client_id_without_a_secret_file(self):
        """The whole point: nothing to place before first boot. A device-flow client's
        only credential is a public client_id, so a profile using it declares no
        required_secrets and `resolve_secrets` never touches the secret store."""
        secrets = GitHubOAuthProvider().resolve_secrets(ProviderConfig.from_dict(_device_raw()))
        assert secrets["client_id"] == "Ov23liEXAMPLE"
        # No `client_secret` KEY at all — a device-flow client does not have a blank
        # secret, it has none. The absence is the assertion (Codacy read an empty
        # literal as a hardcoded credential, and it was not wrong to ask).
        assert "client_secret" not in secrets

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_a_device_entry_without_a_client_id_is_refused(self):
        raw = _device_raw()
        del raw["client_id"]
        with pytest.raises(ProviderError, match="client_id"):
            GitHubOAuthProvider().resolve_secrets(ProviderConfig.from_dict(raw))

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_the_redirect_path_still_fails_closed_without_a_secret(self):
        """The accommodation is scoped to device flow ONLY. An ordinary github_oauth
        entry with no resolvable secret must refuse exactly as it did before — otherwise
        this change would have quietly made every provider secretless."""
        provider = GitHubOAuthProvider()
        config = ProviderConfig.from_dict(_raw())
        with pytest.raises(ProviderError):
            provider.build_allauth_settings(config, {"client_id": "x", "client_secret": ""})

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_a_device_entry_builds_allauth_settings_with_an_empty_secret(self):
        provider = GitHubOAuthProvider()
        config = ProviderConfig.from_dict(_device_raw())
        entry = provider.build_allauth_settings(config, {"client_id": "Ov23liEXAMPLE", "client_secret": ""})
        assert entry["client_id"] == "Ov23liEXAMPLE"
        assert entry["provider_id"] == config.id

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_the_self_test_states_the_posture_rather_than_leaving_it_implicit(self, settings):
        """'This provider signs in without a secret' is exactly the fact an operator
        should read in a boot record, not infer from the absence of something."""
        settings.TAP_AUTH_PROVIDERS = [_device_raw()]
        results = {r.check: r for r in GitHubOAuthProvider().validate_config(ProviderConfig.from_dict(_device_raw()))}
        assert results["device_flow"].status == SelfTestStatus.PASS
        assert "no secret required" in results["device_flow"].message

    @pytest.mark.spec("req-tap-auth-github-device-flow-1")
    def test_an_ordinary_entry_reports_the_device_check_as_skipped(self, settings):
        settings.TAP_AUTH_PROVIDERS = [_raw()]
        results = {r.check: r for r in GitHubOAuthProvider().validate_config(ProviderConfig.from_dict(_raw()))}
        assert results["device_flow"].status == SelfTestStatus.SKIP
